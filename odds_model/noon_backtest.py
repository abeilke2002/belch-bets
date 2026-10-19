"""The honest backtest: only injury information knowable at noon ET, from the official injury reports.

Tonight's absences per team-game, in order of preference:
  1. noon injury report (Out or Doubtful)        2. previous evening's report
  3. the team's previous-game absences (team hadn't filed anything)
The teammates-out and shot-redistribution features are rebuilt from that list, the walk-forward
minutes/points models predict each season from earlier seasons only, and a logistic classifier
(market odds + projection gap + own status + questionable teammates) is compared with the
break-even of the best noon price at your four books. Writes reports/noon_backtest.md.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

from build_features import add_redistribution, teammates_out
from classifier import build_dataset
from config import DATA, REPORTS
from damping import damp, fit_damping, predict_pair
from parse_odds import american_to_decimal, american_to_prob
from regression import fit, load_rows, selected
from selection import clustered_ci
from strategy import evaluate

SEASONS = ['2023-24', '2024-25', '2025-26']
STATUS_RANK = {'Available': 0, 'Probable': 1, 'Questionable': 2, 'Doubtful': 3, 'Out': 4}


def season_averages(played):
    h = played[['PLAYER_ID', 'season', 'GAME_DATE', 'points', 'MINUTES', 'fieldGoalsAttempted']].sort_values('GAME_DATE')
    for c, n in [('points', 'ppg'), ('MINUTES', 'mpg'), ('fieldGoalsAttempted', 'fga')]:
        h[n] = h.groupby(['PLAYER_ID', 'season'])[c].transform(lambda x: x.expanding().mean())
    return h[['PLAYER_ID', 'season', 'GAME_DATE', 'ppg', 'mpg', 'fga']]


def noon_absences(g, played, rep):
    """(player out tonight rows, questionable rows) as known at noon, per team-game."""
    team_games = g[['TEAM_ID', 'season', 'GAME_ID', 'GAME_DATE']].drop_duplicates(['TEAM_ID', 'GAME_ID'])
    team_games = team_games.sort_values('GAME_DATE')
    team_games['prev_game'] = team_games.groupby(['TEAM_ID', 'season'])['GAME_ID'].shift(1)

    reported = rep[['GAME_ID', 'TEAM_ID']].drop_duplicates().assign(has_report=True)
    team_games = team_games.merge(reported, on=['GAME_ID', 'TEAM_ID'], how='left')
    out_report = rep[rep['status'].isin(['Out', 'Doubtful'])][['GAME_ID', 'TEAM_ID', 'PLAYER_ID']]
    questionable = rep[rep['status'] == 'Questionable'][['GAME_ID', 'TEAM_ID', 'PLAYER_ID']]

    actual_out, _ = teammates_out(g, played)                 # who missed each game (used only for "last game")
    prev = actual_out[['PLAYER_ID', 'TEAM_ID', 'GAME_ID']].rename(columns={'GAME_ID': 'prev_game'})
    fallback = team_games[team_games['has_report'].isna()].dropna(subset=['prev_game']) \
        .merge(prev, on=['TEAM_ID', 'prev_game'])[['GAME_ID', 'TEAM_ID', 'PLAYER_ID']]
    out = pd.concat([out_report, fallback], ignore_index=True)
    dates = team_games[['GAME_ID', 'TEAM_ID', 'season', 'GAME_DATE']]
    return out.merge(dates, on=['GAME_ID', 'TEAM_ID']), questionable.merge(dates, on=['GAME_ID', 'TEAM_ID'])


def team_totals(rows, avgs, prefix):
    x = pd.merge_asof(rows.sort_values('GAME_DATE'), avgs.sort_values('GAME_DATE'), on='GAME_DATE',
                      by=['PLAYER_ID', 'season'], allow_exact_matches=False)
    return x.groupby(['GAME_ID', 'TEAM_ID']).agg(**{f'{prefix}ppg': ('ppg', 'sum'), f'{prefix}min': ('mpg', 'sum'),
                                                   f'{prefix}fga': ('fga', 'sum'), f'n_{prefix}': ('PLAYER_ID', 'size')})


def to_md(df):
    cols = [str(c) for c in df.columns]
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def main():
    g = pd.read_parquet(DATA / 'player_games.parquet')
    played = g[g['played']].copy()
    rep = pd.read_parquet(DATA / 'noon_injuries.parquet')
    out_rows, q_rows = noon_absences(g, played, rep)
    avgs = season_averages(played)
    out_t = team_totals(out_rows, avgs, 'out_')
    q_t = team_totals(q_rows, avgs, 'q_').reset_index()[['GAME_ID', 'TEAM_ID', 'q_ppg']]

    df = load_rows()
    noon = df.drop(columns=['out_ppg', 'out_min', 'out_fga', 'n_out']).merge(
        out_t.rename(columns={'out_ppg': 'out_ppg', 'out_min': 'out_min', 'out_fga': 'out_fga', 'n_out_': 'n_out'})
        .reset_index(), on=['GAME_ID', 'TEAM_ID'], how='left')
    noon[['out_ppg', 'out_min', 'out_fga', 'n_out']] = noon[['out_ppg', 'out_min', 'out_fga', 'n_out']].fillna(0)
    noon['out_fga_share'] = noon['out_fga'] / noon['team_fga_pg']
    noon = add_redistribution(noon)

    mf, pf = selected('minutes'), selected('points')
    preds = []
    for s in SEASONS:
        tr = df[df.season < s].copy()
        tr['pred_minutes'] = np.nan
        for t in tr.season.unique():
            m = fit(tr.loc[tr.season != t, mf], tr.loc[tr.season != t, 'MINUTES'])
            tr.loc[tr.season == t, 'pred_minutes'] = m.predict(tr.loc[tr.season == t, mf])
        mm, pm = fit(tr[mf], tr['MINUTES']), fit(tr[pf], tr['points'])
        a, c = fit_damping(df[df.season < s], mf, pf)
        te = noon[noon.season == s]
        raw, no_inj = predict_pair(mm, pm, mf, pf, te)
        preds.append(te[['PLAYER_ID', 'GAME_ID']].assign(pred_noon=no_inj + damp(raw - no_inj, a, c)))
        print(f'{s}: noon projections done', flush=True)
    p = pd.concat(preds)

    d = build_dataset(DATA).merge(p, on=['PLAYER_ID', 'GAME_ID'])
    d = d.merge(q_t, on=['GAME_ID', 'TEAM_ID'], how='left')
    d['q_ppg'] = d['q_ppg'].fillna(0)
    own = rep[['GAME_ID', 'PLAYER_ID', 'status']]
    d = d.merge(own, on=['GAME_ID', 'PLAYER_ID'], how='left')
    d['own_probable'] = (d['status'] == 'Probable').astype(int)
    d['own_questionable'] = d['status'].isin(['Questionable', 'Doubtful']).astype(int)
    # Saved for the line-movement model (all three seasons, noon-knowable only)
    p.to_parquet(DATA / 'noon_projections.parquet', index=False)
    d[['PLAYER_ID', 'GAME_ID', 'q_ppg', 'own_probable', 'own_questionable']].to_parquet(
        DATA / 'noon_injury_feats.parquet', index=False)

    md = ['# Noon-knowable backtest (official injury reports)\n',
          'Each season predicted by models trained on earlier seasons only. Bets at the best noon price '
          'across DraftKings, FanDuel, BetMGM and Caesars; DNPs voided.\n']
    variants = {'gap only': ['logit_novig', 'gap', 'gapz'],
                'gap + own status + questionable teammates': ['logit_novig', 'gap', 'gapz', 'own_probable',
                                                              'own_questionable', 'q_ppg']}
    ll_rows, bet_rows, scored = [], [], []
    for proj_name, col in [('hindsight injuries', 'pred_points'), ('noon injury report', 'pred_noon')]:
        x = d.assign(gap=d[col] - d['line'], gapz=(d[col] - d['line']) / d['pred_sd'])
        for vname, F in variants.items():
            if proj_name.startswith('hindsight') and vname != 'gap only':
                continue
            parts = []
            for s in SEASONS[1:]:
                tr, te = x[x.season < s], x[x.season == s].copy()
                lr = LogisticRegression(max_iter=2000).fit(tr[F], tr['over'])
                te['p_over'] = lr.predict_proba(te[F])[:, 1]
                parts.append(te)
                ll_rows.append({'injury info': proj_name, 'classifier': vname, 'season': s,
                                'market log loss': round(log_loss(te['over'], te['early_novig_over']), 4),
                                'model log loss': round(log_loss(te['over'], te['p_over']), 4)})
            t = pd.concat(parts)
            eo = t['p_over'] - american_to_prob(t['early_best_over_price'])
            eu = (1 - t['p_over']) - american_to_prob(t['early_best_under_price'])
            t['side_over'], t['edge'] = eo >= eu, np.maximum(eo, eu)
            t['score'] = t['edge']
            bet_rows.append(evaluate(t, ks=(1, 3, 5, 999), min_scores=(0.0, 0.02, 0.04),
                                     label=f'{proj_name} | {vname}'))
            scored.append(t.assign(variant=f'{proj_name} | {vname}'))
    bets = pd.concat(bet_rows, ignore_index=True)
    bets['max bets/day'] = bets['max bets/day'].replace(999, 'all')
    md += ['## Log loss vs the market (lower is better)\n', to_md(pd.DataFrame(ll_rows)), '',
           '## Betting: each day, up to N bets with the biggest edge (model P minus break-even of the best price)\n',
           'Flat 1-unit stakes. "all" = every bet over the minimum edge.\n', to_md(bets), '']
    pd.concat(scored).to_parquet(DATA / 'noon_backtest_scored.parquet', index=False)
    (REPORTS / 'noon_backtest.md').write_text('\n'.join(md))
    print('\n'.join(md))


if __name__ == '__main__':
    main()
