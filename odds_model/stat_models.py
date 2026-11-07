"""Rebounds and assists for the live pipeline: train the final models, build tonight's inputs, score the props.

The backtest (stat_backtest.py, no-hindsight version) validated these rules, 2023-26 walk-forward:
  rebounds  unders only     every edge >= 2%: 3,964 bets, 55.4%, +308.6u, +7.8% ROI (each season positive)
  assists   both sides      every edge >= 2%: 1,007 bets, 58.5%, +59.6u, +5.9% ROI
Tonight's inputs come from the backtest's own functions (stat_backtest.player_stat_features, attach_out,
add_new_absence) run on history + tonight's rows, so live and backtest features can't drift apart.

    python stat_models.py train        # -> data/models/stat_models.pkl (a few minutes; rerun after retraining points)
"""
import argparse
import datetime as dt

import joblib
import numpy as np
import pandas as pd

import stat_backtest as SB
from build_features import inferred_absences, load_positions
from classifier import logit, season_weights, sigmoid
from config import DATA
from parse_odds import american_to_prob
from regression import fit, load_rows, minutes_for_season, selected

MODEL_PATH = DATA / 'models' / 'stat_models.pkl'
MARKETS = {'rebounds': {'key': 'reb', 'sides': ('UNDER',), 'clf': ['dlogit']},
           'assists': {'key': 'ast', 'sides': ('OVER', 'UNDER'), 'clf': ['gap', 'gapz']}}


def features_for(key):
    return [f for f in SB.STAT_FEATURES[key] + SB.COMMON if f not in SB.HINDSIGHT]


# ---------------------------------------------------------------- training

def train():
    SB.NO_HINDSIGHT = True
    print('building history...', flush=True)
    hind, _ = SB.build(list(MARKETS), noon_inputs=False)
    mf = [f for f in selected('minutes') if f not in SB.HINDSIGHT]
    hind = hind.reset_index(drop=True)
    hind['pred_minutes'] = minutes_for_season(hind, '9999-99', mf)    # every season predicted by the other seasons
    last = sorted(hind['season'].unique())[-1]
    full = sorted(s for s in hind['season'].unique() if (hind['season'] == s).sum() > 20000)[-1]   # last complete season
    out = {'trained_through': str(hind['GAME_DATE'].max().date())}
    for market, cfg in MARKETS.items():
        key, feats = cfg['key'], features_for(cfg['key'])
        model = SB.fit_stat(hind[feats], hind[key])
        early = hind['season'] < full                                # dispersion: last full season, unseen model
        pm = SB.fit_stat(hind.loc[early, feats], hind.loc[early, key])
        pv = hind[hind['season'] == full]
        edges, rs = SB.dispersion_table(np.maximum(pm.predict(pv[feats]), 0.05), pv[key].values)
        # P(over) weights: market log-odds at weight 1 + the model, recency-weighted over the backtest's props
        props = SB.props(market, pd.read_pickle(DATA / f'stat_preds_{market}_nohind.pkl'), key)
        _, b = SB.fit_offset(props, cfg['clf'])
        out[market] = {'model': model, 'features': feats, 'edges': list(edges), 'rs': list(rs), 'clf_cols': cfg['clf'],
                       'clf_b': [float(x) for x in b], 'sides': cfg['sides']}
        print(f'{market}: {len(hind):,} rows through {last}; dispersion from {full} {np.round(rs, 1).tolist()}; '
              f'P(over) weights {np.round(b, 3).tolist()}', flush=True)
    MODEL_PATH.parent.mkdir(exist_ok=True)
    joblib.dump(out, MODEL_PATH)
    print(f'saved {MODEL_PATH}')


# ---------------------------------------------------------------- tonight's inputs

def history(day):
    """Played rows (this season and last) with rebounds/assists, before `day`."""
    rows = load_rows().merge(SB.box_stats(), on=['GAME_ID', 'PLAYER_ID'], how='inner')
    seasons = sorted(rows['season'].unique())
    from predict_today import season_of
    cur = season_of(day)
    keep = [s for s in seasons if s <= cur][-2:]
    return rows[rows['season'].isin(keep) & (rows['GAME_DATE'] < pd.Timestamp(day))]


def team_now(played, season):
    """Each team's season-to-date averages as of tonight (the un-shifted version of SB.team_context)."""
    p = played[played['season'] == season]
    t = p.groupby(['GAME_ID', 'TEAM_ID', 'OPP_ID'])[['reb', 'ast', 'fieldGoalsAttempted', 'fgm']].sum().reset_index()
    opp = t.rename(columns={'TEAM_ID': 'OPP_ID', 'OPP_ID': 'TEAM_ID', 'reb': 'o_reb', 'ast': 'o_ast',
                            'fieldGoalsAttempted': 'o_fga', 'fgm': 'o_fgm'})
    t = t.merge(opp[['GAME_ID', 'TEAM_ID', 'o_reb', 'o_ast', 'o_fga', 'o_fgm']], on=['GAME_ID', 'TEAM_ID'])
    t['misses'], t['pace'] = t['fieldGoalsAttempted'] - t['fgm'], t['fieldGoalsAttempted'] + t['o_fga']
    return t.groupby('TEAM_ID').agg(reb_allowed=('o_reb', 'mean'), ast_allowed=('o_ast', 'mean'), misses=('misses', 'mean'),
                                    pace=('pace', 'mean'), team_reb=('reb', 'mean'), team_ast=('ast', 'mean')).reset_index()


def tonight_inputs(games, day, fa, weights, keep_out=False):
    """Stat-model inputs for tonight's players. fa: features_as_of + project rows (keep_out=True, with pred_minutes).
    keep_out: also keep players ruled out (the website lets you put them back in). Every row carries reb_out_avg /
    ast_out_avg, what the player takes off the team when he sits (out_stats' merge_asof), so the browser can rebuild
    out_reb / out_ast for any lineup."""
    from predict_today import season_of
    season = season_of(day)
    hist = history(day)
    # every played game (the backtest's played_all), for team context and absent teammates' averages
    played = games[games['played'] & games['season'].isin(hist['season'].unique()) & (games['GAME_DATE'] < pd.Timestamp(day))] \
        .merge(SB.box_stats(), on=['GAME_ID', 'PLAYER_ID'], how='inner')
    tonight = (fa if keep_out else fa[fa['out_w'].fillna(0) < 1]).copy()
    tonight['season'], tonight['GAME_DATE'] = season, pd.Timestamp(day)
    pos = load_positions().set_index('PLAYER_ID')['pos']
    tonight['pos'] = tonight['PLAYER_ID'].map(pos)

    # per-player history features: append tonight as each player's next game (shift(1) => prior games only)
    base = ['PLAYER_ID', 'TEAM_ID', 'GAME_ID', 'season', 'GAME_DATE', 'MINUTES', 'reb', 'oreb', 'ast']
    comb = pd.concat([hist[base], tonight[['PLAYER_ID', 'TEAM_ID', 'GAME_ID', 'season', 'GAME_DATE']]], ignore_index=True)
    ps = SB.player_stat_features(comb)
    stat_cols = [c for c in ps.columns if c not in base]
    ps = ps[ps['GAME_DATE'].eq(pd.Timestamp(day))][['PLAYER_ID'] + stat_cols]
    x = tonight.merge(ps, on='PLAYER_ID', how='left')

    # team context as of tonight
    tn = team_now(played, season)
    x = x.drop(columns=[c for c in ['pace', 'team_reb', 'team_ast'] if c in x]).merge(
        tn[['TEAM_ID', 'pace', 'team_reb', 'team_ast']], on='TEAM_ID', how='left')
    x = x.merge(tn.rename(columns={'TEAM_ID': 'OPP_ID', 'reb_allowed': 'opp_reb_allowed', 'ast_allowed': 'opp_ast_allowed',
                                   'misses': 'opp_misses', 'pace': 'opp_pace'})[
        ['OPP_ID', 'opp_reb_allowed', 'opp_ast_allowed', 'opp_misses', 'opp_pace']], on='OPP_ID', how='left')
    x['misses'] = x['TEAM_ID'].map(tn.set_index('TEAM_ID')['misses'])

    # teammates out tonight (noon weights) and what's usually missing (actual absences, earlier games)
    avgs = SB.stat_averages(played)
    team_of = fa.drop_duplicates('PLAYER_ID').set_index('PLAYER_ID')['TEAM_ID']
    game_of = fa.drop_duplicates('TEAM_ID').set_index('TEAM_ID')['GAME_ID']
    rows = pd.DataFrame([{'PLAYER_ID': p, 'TEAM_ID': team_of[p], 'GAME_ID': game_of[team_of[p]], 'season': season,
                          'GAME_DATE': pd.Timestamp(day), 'weight': w} for p, w in (weights or {}).items() if w > 0 and p in team_of.index])
    if rows.empty:
        rows = pd.DataFrame(columns=['PLAYER_ID', 'TEAM_ID', 'GAME_ID', 'season', 'GAME_DATE', 'weight'])
    x = SB.attach_out(x, rows, avgs, pos)
    me = pd.merge_asof(x[['PLAYER_ID', 'season', 'GAME_DATE']].astype({'GAME_DATE': avgs['GAME_DATE'].dtype}).sort_values('GAME_DATE'),
                       avgs.sort_values('GAME_DATE'),
                       on='GAME_DATE', by=['PLAYER_ID', 'season'], allow_exact_matches=False)
    me = me.drop_duplicates('PLAYER_ID').set_index('PLAYER_ID')
    x['reb_out_avg'] = x['PLAYER_ID'].map(me['reb_avg']).fillna(0)
    x['ast_out_avg'] = x['PLAYER_ID'].map(me['ast_avg']).fillna(0)
    cur = hist[hist['season'] == season].copy()
    if len(cur):
        g = games[(games['season'] == season) & (games['GAME_DATE'] < pd.Timestamp(day))]
        cur['pos'] = cur['PLAYER_ID'].map(pos)
        cur = SB.attach_out(cur, inferred_absences(g).assign(weight=1.0), avgs, pos)
        usual = cur.groupby('PLAYER_ID')[['out_reb', 'out_ast', 'out_reb_pos', 'out_ast_pos']].mean().add_suffix('_usual').reset_index()
    else:
        usual = pd.DataFrame(columns=['PLAYER_ID', 'out_reb_usual', 'out_ast_usual', 'out_reb_pos_usual', 'out_ast_pos_usual'])
    usual['GAME_ID'] = usual['PLAYER_ID'].map(team_of).map(game_of)
    return SB.add_new_absence(x, usual)


# ---------------------------------------------------------------- scoring

def project_tonight(x, models):
    """{market: frame with proj, sd, edges/rs} for tonight's players."""
    out = {}
    for market, m in models.items():
        if market == 'trained_through':
            continue
        y = x[x['out_w'].fillna(0) < 1].copy() if 'out_w' in x else x.copy()
        y['proj'] = np.maximum(m['model'].predict(y[m['features']]), 0.05)
        out[market] = y
    return out


def score_props(y, lines, m, snap='early'):
    """Model P(over) and edges for every prop with a line. Rebounds take unders only (m['sides'])."""
    from name_map import norm
    if lines.empty:
        return pd.DataFrame()
    lines = lines.dropna(subset=[f'{snap}_line']).copy()
    lines['key'] = lines['player'].map(norm)
    d = y.assign(key=y['player_name'].map(norm)).merge(lines.drop(columns=['player']), on='key').drop(columns='key')
    if d.empty:
        return d
    p, sd = SB.p_over(d['proj'].values, d[f'{snap}_line'].values, np.array(m['edges']), np.array(m['rs']))
    d['p_nb'], d['pred_sd'] = np.clip(p, 1e-4, 1 - 1e-4), sd
    d['logit_novig'] = logit(d[f'{snap}_novig_over'])
    d['gap'] = d['proj'] - d[f'{snap}_line']
    d['gapz'] = d['gap'] / d['pred_sd']
    d['dlogit'] = logit(d['p_nb']) - d['logit_novig']
    b = np.array(m['clf_b'])
    d['p_over'] = sigmoid(d['logit_novig'].values + b[0] + d[m['clf_cols']].values @ b[1:])
    d['edge_over'] = d['p_over'] - american_to_prob(d[f'{snap}_best_over_price'])
    d['edge_under'] = (1 - d['p_over']) - american_to_prob(d[f'{snap}_best_under_price'])
    if 'OVER' not in m['sides']:
        d['edge_over'] = -1.0
    if 'UNDER' not in m['sides']:
        d['edge_under'] = -1.0
    d['edge'] = np.maximum(d['edge_over'], d['edge_under'])
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['train'])
    ap.parse_args()
    train()


if __name__ == '__main__':
    main()
