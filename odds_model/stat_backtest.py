"""Rebounds and assists: projection -> count distribution -> P(over the noon line), walk-forward 2023-26.

Built from the same pieces as points, so all three markets are judged alike:
  minutes   the current minutes model (selected('minutes')), retrained per test season on earlier seasons and
            predicted from noon inputs (noon injury report, Questionable at half), as q_policy_test does for points
  stat      LightGBM (Poisson) on minutes x rate: per-game and per-minute rebounds/assists (season, last 10/5/3),
            last season, role, rest, opponent allowed + missed shots + pace, spread/total, and teammates out
            (their rebounds/assists overall and at his position, vs what's usually missing)
  counts    negative binomial around the projection; dispersion per projection bin, fit on the season before
            the test season (no peeking)
  P(over)   market log-odds kept at weight 1, plus the projection (gap, gap/sd) or the count model's own
            probability, recency-weighted, as classifier.py does for points
Scored on log loss vs the market, calibration, and units under the live rule (every eligible prop with edge
>= 2% at the best price, flat 1u; skip players on the noon report and back-to-backs).

    python stat_backtest.py                  # both stats -> reports/stat_backtest.md, data/stat_preds_{stat}.parquet
    python stat_backtest.py --stats rebounds
"""
import argparse

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.special import gammaln
from scipy.stats import nbinom
from sklearn.metrics import log_loss

from build_features import add_redistribution, finish_position, inferred_absences, load_positions, position_absences
from classifier import logit, season_weights, sigmoid
from config import BOOKS, CSV_DIR, DATA, REPORTS
from noon_backtest import season_averages
from parse_odds import american_to_decimal, american_to_prob
from q_policy_test import absence_lists, weighted_totals
from regression import PARAMS, fit, load_rows, minutes_for_season, selected

import lightgbm as lgb

STATS = {'rebounds': 'reb', 'assists': 'ast'}
TEST_SEASONS = ['2023-24', '2024-25', '2025-26']
PLAN = [('2024-25', ['2023-24']), ('2025-26', ['2023-24', '2024-25']), ('2023-24', ['2024-25', '2025-26'])]
ON_REPORT = {'Probable', 'Questionable', 'Doubtful'}
MIN_EDGE = 0.02


# ---------------------------------------------------------------- data

def box_stats():
    """Rebounds, offensive rebounds, assists, FGM per player-game from the raw box files (2018-26)."""
    cols = ['GAME_ID', 'PLAYER_ID', 'reboundsTotal', 'reboundsOffensive', 'assists', 'fieldGoalsMade']
    frames = [pd.read_csv(f, usecols=lambda c: c in cols, dtype={'GAME_ID': str}, low_memory=False)
              for f in sorted(CSV_DIR.glob('*all_box.csv'))]
    b = pd.concat([f for f in frames if 'reboundsTotal' in f], ignore_index=True)
    b['GAME_ID'] = b['GAME_ID'].str.lstrip('0')
    return b.drop_duplicates(['GAME_ID', 'PLAYER_ID']).rename(
        columns={'reboundsTotal': 'reb', 'reboundsOffensive': 'oreb', 'assists': 'ast', 'fieldGoalsMade': 'fgm'})


def player_stat_features(d):
    """Prior-games-only averages per player-season (shift(1)), plus last season's per-game average.
    All rolling features are computed on one sorted, freshly indexed frame before any merge (a merge renumbers rows,
    which would misalign groupby results computed earlier)."""
    d = d.sort_values(['PLAYER_ID', 'GAME_DATE']).reset_index(drop=True)
    g = d.groupby(['PLAYER_ID', 'season'])
    mins = g['MINUTES'].transform(lambda x: x.shift(1).cumsum())
    m10 = g['MINUTES'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).sum())
    for s in ['reb', 'ast', 'oreb']:
        d[f'{s}_season'] = g[s].transform(lambda x: x.shift(1).expanding().mean())
        for w in (10, 5, 3):
            d[f'{s}_{w}'] = g[s].transform(lambda x, w=w: x.shift(1).rolling(w, min_periods=1).mean())
        d[f'{s}_pm_season'] = g[s].transform(lambda x: x.shift(1).cumsum()) / mins.where(mins > 0)
        d[f'{s}_pm_10'] = g[s].transform(lambda x: x.shift(1).rolling(10, min_periods=1).sum()) / m10.where(m10 > 0)
    d['oreb_share'] = d['oreb_season'] / d['reb_season'].where(d['reb_season'] > 0)
    order = sorted(d['season'].unique())
    nxt = {a: b for a, b in zip(order, order[1:])}
    prev = d.groupby(['PLAYER_ID', 'season'])[['reb', 'ast', 'oreb']].mean().add_suffix('_prev').reset_index()
    prev['season'] = prev['season'].map(nxt)
    return d.merge(prev.dropna(subset=['season']), on=['PLAYER_ID', 'season'], how='left')


def team_context(played):
    """Per team-game: what the team allows (opponents' rebounds/assists, missed shots) and pace, prior games only."""
    t = played.groupby(['GAME_ID', 'TEAM_ID', 'OPP_ID', 'season', 'GAME_DATE'])[
        ['reb', 'ast', 'fieldGoalsAttempted', 'fgm']].sum().reset_index()
    opp = t.rename(columns={'TEAM_ID': 'OPP_ID', 'OPP_ID': 'TEAM_ID', 'reb': 'o_reb', 'ast': 'o_ast',
                            'fieldGoalsAttempted': 'o_fga', 'fgm': 'o_fgm'})
    t = t.merge(opp[['GAME_ID', 'TEAM_ID', 'o_reb', 'o_ast', 'o_fga', 'o_fgm']], on=['GAME_ID', 'TEAM_ID'])
    t['miss'] = t['fieldGoalsAttempted'] - t['fgm']             # this team's misses: rebounds for the boards
    t['o_miss'] = t['o_fga'] - t['o_fgm']
    t['pace'] = t['fieldGoalsAttempted'] + t['o_fga']
    t = t.sort_values('GAME_DATE')
    g = t.groupby(['TEAM_ID', 'season'])
    out = t[['GAME_ID', 'TEAM_ID']].copy()
    for c, n in [('o_reb', 'reb_allowed'), ('o_ast', 'ast_allowed'), ('miss', 'misses'), ('o_miss', 'misses_allowed'),
                 ('pace', 'pace'), ('reb', 'team_reb'), ('ast', 'team_ast')]:
        out[n] = g[c].transform(lambda x: x.shift(1).expanding().mean())
    return out


def stat_averages(played):
    h = played[['PLAYER_ID', 'season', 'GAME_DATE', 'reb', 'ast']].sort_values('GAME_DATE').copy()
    for c in ['reb', 'ast']:
        h[f'{c}_avg'] = h.groupby(['PLAYER_ID', 'season'])[c].transform(lambda x: x.expanding().mean())
    return h[['PLAYER_ID', 'season', 'GAME_DATE', 'reb_avg', 'ast_avg']]


def out_stats(rows, avgs, pos):
    """Absent teammates' rebounds/assists (weighted), overall and by position, per team-game."""
    x = pd.merge_asof(rows.sort_values('GAME_DATE'), avgs.sort_values('GAME_DATE'), on='GAME_DATE',
                      by=['PLAYER_ID', 'season'], allow_exact_matches=False)
    x['pos'] = x['PLAYER_ID'].map(pos)
    for c in ['reb_avg', 'ast_avg']:
        x[c] = x[c].fillna(0) * x['weight']
    tot = x.groupby(['GAME_ID', 'TEAM_ID'])[['reb_avg', 'ast_avg']].sum().rename(
        columns={'reb_avg': 'out_reb', 'ast_avg': 'out_ast'}).reset_index()
    bypos = x.groupby(['GAME_ID', 'TEAM_ID', 'pos'])[['reb_avg', 'ast_avg']].sum().rename(
        columns={'reb_avg': 'out_reb_pos', 'ast_avg': 'out_ast_pos'}).reset_index()
    return tot, bypos


def attach_out(df, rows, avgs, pos):
    tot, bypos = out_stats(rows, avgs, pos)
    df = df.drop(columns=['out_reb', 'out_ast', 'out_reb_pos', 'out_ast_pos'], errors='ignore')
    df = df.merge(tot, on=['GAME_ID', 'TEAM_ID'], how='left').merge(bypos, on=['GAME_ID', 'TEAM_ID', 'pos'], how='left')
    for c in ['out_reb', 'out_ast', 'out_reb_pos', 'out_ast_pos']:
        df[c] = df[c].fillna(0)
    return df


def add_new_absence(df, usual):
    """How much of tonight's missing rebounds/assists is new (beyond what was usually missing in his earlier games),
    and his expected share of it."""
    df = df.merge(usual, on=['PLAYER_ID', 'GAME_ID'], how='left')
    for s in ['reb', 'ast']:
        new = df[f'out_{s}'] - df[f'out_{s}_usual'].fillna(0)
        new_pos = df[f'out_{s}_pos'] - df[f'out_{s}_pos_usual'].fillna(0)
        share = df[f'{s}_season'] / df[f'team_{s}'].where(df[f'team_{s}'] > 0)
        df[f'new_out_{s}'], df[f'new_out_{s}_pos'] = new, new_pos
        df[f'exp_extra_{s}'] = new * share
    return df


POSITION = ['out_min_pos', 'n_active_pos', 'n_rot_pos', 'pos_vacancy']


def noon_positions(df, g, rows):
    """out_min_pos / n_active_pos / pos_vacancy from the noon report instead of who actually sat: everyone on the
    team-game (dressed, absent or listed) at his noon weight (0 if not listed), season-to-date mpg from earlier games.
    The same inputs predict_today builds live (position_absences over the roster at out_w)."""
    played = g[g['played']]
    mpg = played[['PLAYER_ID', 'season', 'GAME_DATE', 'MINUTES']].sort_values(['PLAYER_ID', 'GAME_DATE']).copy()
    mpg['mpg'] = mpg.groupby(['PLAYER_ID', 'season'])['MINUTES'].transform(lambda x: x.expanding().mean())
    mpg = mpg.drop(columns='MINUTES').sort_values('GAME_DATE')
    cols = ['PLAYER_ID', 'season', 'GAME_ID', 'TEAM_ID', 'GAME_DATE']
    rost = pd.concat([g.loc[g['played'] | g['cd_dnp'], cols], inferred_absences(g)[cols], rows[cols]]) \
             .drop_duplicates(['GAME_ID', 'PLAYER_ID'])
    w = rows.groupby(['GAME_ID', 'PLAYER_ID'])['weight'].max()
    rost['w'] = pd.Series(list(zip(rost['GAME_ID'], rost['PLAYER_ID']))).map(w).fillna(0.0).values
    rost = pd.merge_asof(rost.sort_values('GAME_DATE'), mpg, on='GAME_DATE', by=['PLAYER_ID', 'season'],
                         allow_exact_matches=False).merge(load_positions(), on='PLAYER_ID', how='left')
    df = df.drop(columns=[c for c in POSITION if c in df]).merge(position_absences(rost), on=['GAME_ID', 'TEAM_ID', 'pos'], how='left')
    return finish_position(df)


def build(stat_list, noon_inputs=True):
    g = pd.read_parquet(DATA / 'player_games.parquet')
    played_all = g[g['played']].merge(box_stats(), on=['GAME_ID', 'PLAYER_ID'], how='left')
    played_all = played_all.dropna(subset=['reb', 'ast'])         # 2026-27 (ESPN) rows have no rebounds/assists yet
    df = load_rows(min_gp=0).merge(box_stats(), on=['GAME_ID', 'PLAYER_ID'], how='inner')   # first games count toward averages
    df = player_stat_features(df)
    df = df.merge(team_context(played_all), on=['GAME_ID', 'TEAM_ID'], how='left')
    opp = team_context(played_all).rename(columns={'TEAM_ID': 'OPP_ID'})[
        ['GAME_ID', 'OPP_ID', 'reb_allowed', 'ast_allowed', 'misses', 'pace']].rename(
        columns={'reb_allowed': 'opp_reb_allowed', 'ast_allowed': 'opp_ast_allowed', 'misses': 'opp_misses', 'pace': 'opp_pace'})
    df = df.merge(opp, on=['GAME_ID', 'OPP_ID'], how='left')

    pos = load_positions().set_index('PLAYER_ID')['pos']
    avgs = stat_averages(played_all)
    actual = inferred_absences(g).assign(weight=1.0)[['GAME_ID', 'TEAM_ID', 'PLAYER_ID', 'season', 'GAME_DATE', 'weight']]
    df = attach_out(df, actual, avgs, pos)
    # what was usually missing in his earlier games (actual absences, prior games only)
    u = df[['PLAYER_ID', 'GAME_ID', 'season', 'GAME_DATE', 'out_reb', 'out_ast', 'out_reb_pos', 'out_ast_pos']].sort_values('GAME_DATE')
    gg = u.groupby(['PLAYER_ID', 'season'])
    usual = u[['PLAYER_ID', 'GAME_ID']].copy()
    for c in ['out_reb', 'out_ast', 'out_reb_pos', 'out_ast_pos']:
        usual[f'{c}_usual'] = gg[c].transform(lambda x: x.shift(1).expanding().mean())
    hind = add_new_absence(df, usual)
    if not noon_inputs:
        return hind[hind['gp'] >= 1].reset_index(drop=True), None         # a first game has no history to predict from

    # noon inputs: the noon report (Questionable at half) for teammates-out, everything else unchanged
    rep = pd.read_parquet(DATA / 'noon_injuries.parquet')
    rows = absence_lists(g, g[g['played']], rep)['half']
    noon = attach_out(df, rows, avgs, pos)
    wt = weighted_totals(rows, season_averages(g[g['played']]))
    noon = noon.drop(columns=['out_ppg', 'out_min', 'out_fga', 'n_out']).merge(wt, on=['GAME_ID', 'TEAM_ID'], how='left')
    noon[['out_ppg', 'out_min', 'out_fga', 'n_out']] = noon[['out_ppg', 'out_min', 'out_fga', 'n_out']].fillna(0)
    noon['out_fga_share'] = noon['out_fga'] / noon['team_fga_pg']
    noon = noon_positions(noon, g, rows)                       # position absences from the report too
    noon = add_new_absence(add_redistribution(noon), usual)
    return hind[hind['gp'] >= 1].reset_index(drop=True), noon[noon['gp'] >= 1].reset_index(drop=True)


STAT_FEATURES = {
    'reb': ['reb_season', 'reb_10', 'reb_5', 'reb_3', 'reb_pm_season', 'reb_pm_10', 'reb_prev', 'oreb_season', 'oreb_share',
            'opp_reb_allowed', 'opp_misses', 'misses', 'team_reb', 'out_reb', 'out_reb_pos', 'new_out_reb', 'new_out_reb_pos',
            'exp_extra_reb'],
    'ast': ['ast_season', 'ast_10', 'ast_5', 'ast_3', 'ast_pm_season', 'ast_pm_10', 'ast_prev',
            'opp_ast_allowed', 'team_ast', 'out_ast', 'out_ast_pos', 'new_out_ast', 'new_out_ast_pos', 'exp_extra_ast',
            'usage_share'],
}
COMMON = ['pred_minutes', 'min_season', 'min_5', 'start_rate', 'started_last', 'rest_days', 'gp', 'pace', 'opp_pace',
          'out_min', 'n_out', 'out_min_pos', 'pos_vacancy', 'pos_code', 'team_spread', 'abs_spread', 'total', 'team_implied',
          'opp_out_min', 'opp_out_ppg', 'opp_out_min_pos', 'ret_min', 'ret_min_pos', 'n_active_pos']
# --no-hindsight (the first live version) dropped these. Only the three position ones were ever built from who
# actually sat, and noon_positions now rebuilds them from the noon report for test rows; ret_* and opp_out_* come
# from game_context.py, which builds them from the noon reports. So the full set is leak-free (--tag _noon).
HINDSIGHT = ['out_min_pos', 'n_active_pos', 'pos_vacancy', 'ret_min', 'ret_min_pos', 'opp_out_min', 'opp_out_ppg',
             'opp_out_min_pos']
NO_HINDSIGHT = False
MONO = {'pred_minutes': 1, 'new_out_reb_pos': 1, 'new_out_ast_pos': 1, 'exp_extra_reb': 1, 'exp_extra_ast': 1}


def fit_stat(X, y):
    p = dict(PARAMS, objective='poisson', verbose=-1)
    p['monotone_constraints'] = [MONO.get(c, 0) for c in X.columns]
    return lgb.LGBMRegressor(**p).fit(X, y)


# ---------------------------------------------------------------- counts

def nb_r(mu, y):
    """MLE of the negative binomial size r (var = mu + mu^2/r); large r ~ Poisson."""
    def nll(lr):
        r = np.exp(lr)
        return -(gammaln(y + r) - gammaln(r) - gammaln(y + 1) + r * np.log(r / (r + mu)) + y * np.log(mu / (r + mu))).mean()
    return float(np.exp(minimize_scalar(nll, bounds=(-1, 7), method='bounded').x))


def dispersion_table(mu, y, bins=8):
    edges = np.unique(np.quantile(mu, np.linspace(0, 1, bins + 1)))
    idx = np.clip(np.digitize(mu, edges[1:-1]), 0, len(edges) - 2)
    return edges, np.array([nb_r(mu[idx == i], y[idx == i]) for i in range(len(edges) - 1)])


def p_over(mu, line, edges, rs):
    r = rs[np.clip(np.digitize(mu, edges[1:-1]), 0, len(rs) - 1)]
    k = np.floor(line)                                         # .5 lines: over = at least floor(line) + 1
    return nbinom.sf(k, r, r / (r + mu)), np.sqrt(mu + mu ** 2 / r)


# ---------------------------------------------------------------- projections, walk-forward

def project(hind, noon, s_key):
    """Noon projections for every test season: model trained on earlier seasons only."""
    mf = [f for f in selected('minutes') if not (NO_HINDSIGHT and f in HINDSIGHT)]
    feats = [f for f in STAT_FEATURES[s_key] + COMMON if not (NO_HINDSIGHT and f in HINDSIGHT)]
    out = []
    for s in TEST_SEASONS:
        h = hind[hind['season'] <= s].reset_index(drop=True)
        h['pred_minutes'] = minutes_for_season(h, s, mf)        # leave-one-season-out on training rows
        mm = fit(h.loc[h['season'] < s, mf], h.loc[h['season'] < s, 'MINUTES'])
        te = noon[noon['season'] == s].copy()
        te['pred_minutes'] = mm.predict(te[mf])
        tr = h[h['season'] < s]
        model = fit_stat(tr[feats], tr[s_key])
        te['proj'] = model.predict(te[feats])
        # dispersion from the season before s, projected by a model that hadn't seen it
        prev = sorted(tr['season'].unique())[-1]
        pm = fit_stat(tr.loc[tr['season'] < prev, feats], tr.loc[tr['season'] < prev, s_key])
        pv = tr[tr['season'] == prev]
        edges, rs = dispersion_table(np.maximum(pm.predict(pv[feats]), 0.05), pv[s_key].values)
        te['r_edges'], te['r_vals'] = [list(edges)] * len(te), [list(rs)] * len(te)
        out.append(te[['PLAYER_ID', 'GAME_ID', 'season', 'GAME_DATE', 'rest_days', s_key, 'pred_minutes', 'proj',
                       'r_edges', 'r_vals']])
        print(f'  {s_key} {s}: trained on {len(tr):,} rows, dispersion r by bin {np.round(rs, 1).tolist()}', flush=True)
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------- vs the market

def props(stat, preds, s_key):
    lines = pd.read_parquet(DATA / f'odds_lines_{stat}.parquet').dropna(subset=['early_line']).drop(columns=['season'])
    nm = pd.read_parquet(DATA / 'name_map_extra.parquet').dropna(subset=['PLAYER_ID'])
    d = lines.merge(nm[['event_id', 'player', 'GAME_ID', 'PLAYER_ID']], on=['event_id', 'player'])
    d['PLAYER_ID'] = d['PLAYER_ID'].astype(int)
    d = d.merge(preds, on=['GAME_ID', 'PLAYER_ID'])            # played games only (DNP props void)
    d = d[d[s_key] != d['early_line']].copy()                  # pushes
    d['over'] = (d[s_key] > d['early_line']).astype(int)
    p, sd = [], []
    for e, r, mu, ln in zip(d['r_edges'], d['r_vals'], d['proj'], d['early_line']):
        a, b = p_over(np.array([max(mu, 0.05)]), np.array([ln]), np.array(e), np.array(r))
        p.append(a[0]); sd.append(b[0])
    d['p_nb'], d['sd'] = np.clip(p, 1e-4, 1 - 1e-4), sd
    d['logit_novig'] = logit(d['early_novig_over'])
    d['gap'] = d['proj'] - d['early_line']
    d['gapz'] = d['gap'] / d['sd']
    d['dlogit'] = logit(d['p_nb']) - d['logit_novig']
    st = pd.read_parquet(DATA / 'noon_injuries.parquet')[['GAME_ID', 'PLAYER_ID', 'status']].drop_duplicates(['GAME_ID', 'PLAYER_ID'])
    return d.merge(st, on=['GAME_ID', 'PLAYER_ID'], how='left')


def fit_offset(tr, cols):
    X, off, y = tr[cols].values, tr['logit_novig'].values, tr['over'].values
    w = season_weights(tr['season'])
    def nll(b):
        p = np.clip(sigmoid(off + b[0] + X @ b[1:]), 1e-6, 1 - 1e-6)
        return -(w * (y * np.log(p) + (1 - y) * np.log(1 - p))).sum() / w.sum()
    b = minimize(nll, np.zeros(len(cols) + 1), method='BFGS').x
    return lambda x: sigmoid(x['logit_novig'].values + b[0] + x[cols].values @ b[1:]), b


def evaluate(d, cols, label):
    parts, coefs = [], []
    for test, train in PLAN:
        te = d[d['season'] == test].copy()
        f, b = fit_offset(d[d['season'].isin(train)], cols)
        te['p'] = f(te)
        parts.append(te); coefs.append(f"{test}: {np.round(b[1:], 3).tolist()}")
    t = pd.concat(parts)
    eo = t['p'] - american_to_prob(t['early_best_over_price'])
    eu = (1 - t['p']) - american_to_prob(t['early_best_under_price'])
    t['side_over'], t['edge'] = eo >= eu, np.maximum(eo, eu)
    t['p_side'] = np.where(t['side_over'], t['p'], 1 - t['p'])
    t['price'] = np.where(t['side_over'], t['early_best_over_price'], t['early_best_under_price'])
    t['win'] = np.where(t['side_over'], t['over'] == 1, t['over'] == 0)
    gain = {s: (log_loss(x['over'], x['early_novig_over']) - log_loss(x['over'], x['p'])) * 1e4 for s, x in t.groupby('season')}
    el = t[~t['status'].isin(ON_REPORT) & (t['rest_days'] != 1)]
    rows = []
    for rule, b in [('every edge >= 2%, 1u', el[el['edge'] >= MIN_EDGE]),
                    ('top 1 a day, >= 2%', el.sort_values('edge', ascending=False).drop_duplicates('GAME_DATE').query('edge >= @MIN_EDGE'))]:
        u = np.where(b['win'], american_to_decimal(b['price']) - 1, -1.0)
        per = ' / '.join(f"{u[(b['season'] == s).values].sum():+.1f}" for s in TEST_SEASONS)
        rows.append({'version': label, 'rule': rule, 'bets': len(b), 'pred / won': f"{b['p_side'].mean():.1%} / {b['win'].mean():.1%}",
                     'units': f'{u.sum():+.1f}', 'ROI': f'{u.sum() / max(len(b), 1):+.1%}', '23-24 / 24-25 / 25-26': per,
                     'unders': f"{(~b['side_over']).mean():.0%}"})
    return t, rows, gain, coefs


def to_md(df):
    cols = [str(c) for c in df.columns]
    o = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(o + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stats', nargs='+', default=list(STATS))
    ap.add_argument('--reuse', action='store_true', help='reuse saved projections (scoring changes only)')
    ap.add_argument('--no-hindsight', action='store_true', help='drop inputs built from who actually sat')
    ap.add_argument('--tag', default='', help='suffix for saved projections and the report')
    args = ap.parse_args()
    global NO_HINDSIGHT
    NO_HINDSIGHT = args.no_hindsight
    if args.reuse and all((DATA / f'stat_preds_{s}{args.tag}.pkl').exists() for s in args.stats):
        hind = noon = None
    else:
        print('building features...', flush=True)
        hind, noon = build(args.stats)
    md = ['# Rebounds and assists backtest\n', 'Walk-forward 2023-26; noon injury report (Questionable at half); '
          'market log-odds kept at weight 1.\n']
    for stat in args.stats:
        s_key = STATS[stat]
        cache = DATA / f'stat_preds_{stat}{args.tag}.pkl'
        if args.reuse and cache.exists():
            preds = pd.read_pickle(cache)
        else:
            preds = project(hind, noon, s_key)
            preds.to_pickle(cache)
        preds.drop(columns=['r_edges', 'r_vals']).to_parquet(DATA / f'stat_preds_{stat}{args.tag}.parquet', index=False)
        acc = preds.assign(e=preds[s_key] - preds['proj'])
        d = props(stat, preds, s_key)
        md += [f'## {stat.capitalize()}\n',
               f"Projection error (all games): RMSE {np.sqrt((acc['e'] ** 2).mean()):.2f}, bias {acc['e'].mean():+.2f}. "
               f"Props matched: {len(d):,}; over rate {d['over'].mean():.1%}.\n",
               f"Projection vs line: projection closer to the actual than the line on "
               f"{((d['proj'] - d[s_key]).abs() < (d['early_line'] - d[s_key]).abs()).mean():.1%} of props.\n"]
        rows, gains = [], []
        for cols, label in [(['gap', 'gapz'], 'projection gap'), (['dlogit'], 'count-model probability')]:
            t, r, gain, coefs = evaluate(d, cols, label)
            rows += r
            gains.append({'version': label, **{f'beats market {s} (x1e-4)': f'{v:+.1f}' for s, v in sorted(gain.items())},
                          'weights by fold': '; '.join(coefs)})
        md += [to_md(pd.DataFrame(gains)), '', to_md(pd.DataFrame(rows)), '']
        print('\n'.join(md[-4:]), flush=True)
    (REPORTS / f'stat_backtest{args.tag}.md').write_text('\n'.join(md))


if __name__ == '__main__':
    main()
