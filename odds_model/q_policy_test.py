"""How should a Questionable teammate count at noon? Three policies for tonight's absence list:
  active      Questionable = plays (current)
  prev game   Questionable = out if he missed the team's previous game, else plays
  half        Questionable counts 50% toward the teammates-out totals (they play ~49% of the time)
Out/Doubtful are always out. Models are trained once per season; only tonight's inputs change.
Scored with the noon classifier, the filters (skip players on the report, skip back-to-backs) and
top 1/3 bets per day, for 2024-25 + 2025-26 (walk-forward) and 2023-24 (classifier fit on 2024-26).
Writes reports/q_policy_test.md.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from build_features import add_redistribution, teammates_out
from classifier import build_dataset
from config import DATA, REPORTS
from damping import damp, fit_damping, predict_pair
from noon_backtest import season_averages
from parse_odds import american_to_prob
from regression import fit, load_rows, selected
from strategy import evaluate

SEASONS = ['2023-24', '2024-25', '2025-26']
ON_REPORT = {'Probable', 'Questionable', 'Doubtful'}


def absence_lists(g, played, rep):
    """Weighted absence rows (GAME_ID, TEAM_ID, PLAYER_ID, weight) per policy."""
    tg = g[['TEAM_ID', 'season', 'GAME_ID', 'GAME_DATE']].drop_duplicates(['TEAM_ID', 'GAME_ID']).sort_values('GAME_DATE')
    tg['prev_game'] = tg.groupby(['TEAM_ID', 'season'])['GAME_ID'].shift(1)
    actual_out, _ = teammates_out(g, played)
    prev_out = set(zip(actual_out['PLAYER_ID'], actual_out['GAME_ID']))

    rep = rep.merge(tg[['GAME_ID', 'TEAM_ID', 'prev_game']], on=['GAME_ID', 'TEAM_ID'])
    rep['missed_prev'] = [(p, pg) in prev_out for p, pg in zip(rep['PLAYER_ID'], rep['prev_game'])]
    hard = rep[rep['status'].isin(['Out', 'Doubtful'])].assign(weight=1.0)
    q = rep[rep['status'] == 'Questionable']

    # teams with no report at noon: previous-game absences (same as noon_backtest)
    reported = rep[['GAME_ID', 'TEAM_ID']].drop_duplicates().assign(has=True)
    tg2 = tg.merge(reported, on=['GAME_ID', 'TEAM_ID'], how='left')
    prev = actual_out[['PLAYER_ID', 'TEAM_ID', 'GAME_ID']].rename(columns={'GAME_ID': 'prev_game'})
    fallback = tg2[tg2['has'].isna()].dropna(subset=['prev_game']).merge(prev, on=['TEAM_ID', 'prev_game']) \
        .assign(weight=1.0)

    cols = ['GAME_ID', 'TEAM_ID', 'PLAYER_ID', 'weight']
    base = pd.concat([hard[cols], fallback[cols]], ignore_index=True)
    # Crystal ball for listed players only: Questionable/Doubtful/Probable resolved to what actually happened.
    # Players not on the noon report are still assumed to play (no knowledge of unlisted late scratches).
    played_set = set(zip(played['PLAYER_ID'], played['GAME_ID']))
    listed = rep[rep['status'].isin(['Questionable', 'Doubtful', 'Probable'])].copy()
    listed['sat'] = [(p, gm) not in played_set for p, gm in zip(listed['PLAYER_ID'], listed['GAME_ID'])]
    resolved = pd.concat([rep[rep['status'] == 'Out'].assign(weight=1.0)[cols], fallback[cols],
                          listed[listed['sat']].assign(weight=1.0)[cols]], ignore_index=True)
    policies = {'active': base, 'listed players resolved (crystal ball)': resolved,
                'prev game': pd.concat([base, q[q['missed_prev']].assign(weight=1.0)[cols]], ignore_index=True),
                'half': pd.concat([base, q.assign(weight=0.5)[cols]], ignore_index=True)}
    dates = tg[['GAME_ID', 'TEAM_ID', 'season', 'GAME_DATE']]
    return {k: v.merge(dates, on=['GAME_ID', 'TEAM_ID']) for k, v in policies.items()}


def weighted_totals(rows, avgs):
    x = pd.merge_asof(rows.sort_values('GAME_DATE'), avgs.sort_values('GAME_DATE'), on='GAME_DATE',
                      by=['PLAYER_ID', 'season'], allow_exact_matches=False)
    for c in ['ppg', 'mpg', 'fga']:
        x[c] = x[c] * x['weight']
    return x.groupby(['GAME_ID', 'TEAM_ID']).agg(out_ppg=('ppg', 'sum'), out_min=('mpg', 'sum'),
                                                 out_fga=('fga', 'sum'), n_out=('weight', 'sum')).reset_index()


def to_md(df):
    cols = [str(c) for c in df.columns]
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def main():
    g = pd.read_parquet(DATA / 'player_games.parquet')
    played = g[g['played']].copy()
    rep = pd.read_parquet(DATA / 'noon_injuries.parquet')
    avgs = season_averages(played)
    lists = absence_lists(g, played, rep)

    df = load_rows()
    inputs = {}
    for name, rows in lists.items():
        x = df.drop(columns=['out_ppg', 'out_min', 'out_fga', 'n_out']).merge(
            weighted_totals(rows, avgs), on=['GAME_ID', 'TEAM_ID'], how='left')
        x[['out_ppg', 'out_min', 'out_fga', 'n_out']] = x[['out_ppg', 'out_min', 'out_fga', 'n_out']].fillna(0)
        x['out_fga_share'] = x['out_fga'] / x['team_fga_pg']
        inputs[name] = add_redistribution(x)

    mf, pf = selected('minutes'), selected('points')
    preds = {k: [] for k in inputs}
    for s in SEASONS:
        tr = df[df.season < s].copy()
        tr['pred_minutes'] = np.nan
        for t in tr.season.unique():
            m = fit(tr.loc[tr.season != t, mf], tr.loc[tr.season != t, 'MINUTES'])
            tr.loc[tr.season == t, 'pred_minutes'] = m.predict(tr.loc[tr.season == t, mf])
        mm, pm = fit(tr[mf], tr['MINUTES']), fit(tr[pf], tr['points'])
        a, c = fit_damping(df[df.season < s], mf, pf)
        for name, x in inputs.items():
            te = x[x.season == s]
            raw, no_inj = predict_pair(mm, pm, mf, pf, te)
            preds[name].append(te[['PLAYER_ID', 'GAME_ID', 'points']].assign(pred=no_inj + damp(raw - no_inj, a, c)))
        print(f'{s}: models trained, three policies predicted', flush=True)

    base = build_dataset(DATA)
    status = rep[['GAME_ID', 'PLAYER_ID', 'status']].drop_duplicates(['GAME_ID', 'PLAYER_ID'])
    base = base.merge(status, on=['GAME_ID', 'PLAYER_ID'], how='left')
    acc, bets = [], []
    F = ['logit_novig', 'gap', 'gapz']
    for name, p in preds.items():
        p = pd.concat(p)
        if name == 'half':
            p.to_parquet(DATA / 'noon_projections_half.parquet', index=False)   # the production policy
        acc.append({'policy': name, 'RMSE points (2023-26, noon inputs)': round(float(np.sqrt(((p.pred - p.points) ** 2).mean())), 4)})
        d = base.merge(p[['PLAYER_ID', 'GAME_ID', 'pred']], on=['PLAYER_ID', 'GAME_ID'])
        d = d.assign(gap=d['pred'] - d['line'], gapz=(d['pred'] - d['line']) / d['pred_sd'])
        parts = []
        for test, train in [('2024-25', ['2023-24']), ('2025-26', ['2023-24', '2024-25']), ('2023-24', ['2024-25', '2025-26'])]:
            tr, te = d[d.season.isin(train)], d[d.season == test].copy()
            te['p'] = LogisticRegression(max_iter=2000).fit(tr[F], tr['over']).predict_proba(te[F])[:, 1]
            parts.append(te)
        t = pd.concat(parts)
        eo = t['p'] - american_to_prob(t['early_best_over_price'])
        eu = (1 - t['p']) - american_to_prob(t['early_best_under_price'])
        t['side_over'], t['score'] = eo >= eu, np.maximum(eo, eu)
        t = t[~t['status'].isin(ON_REPORT) & (t['rest_days'] != 1)]
        bets.append(evaluate(t, ks=(1, 3), min_scores=(0.02,), label=f'Q = {name}'))
    b = pd.concat(bets, ignore_index=True)
    cols = ['strategy', 'max bets/day', 'min score', 'bets', 'win %', 'ROI', 'units 2023-24', 'units 2024-25',
            'units 2025-26', 'units total', 'max drawdown (u)', 'line moved our way / against']
    md = ['# How to count Questionable teammates at noon\n',
          'Same models, three ways of building tonight\'s absence list. Bets: noon classifier, skip players on the '
          'report and back-to-backs, best price among your four books, flat 1u. 2023-24 uses a classifier fit on '
          '2024-26 (fresh season); the other two are walk-forward.\n',
          to_md(pd.DataFrame(acc)), '', to_md(b[[c for c in cols if c in b]]), '']
    (REPORTS / 'q_policy_test.md').write_text('\n'.join(md))
    print('\n'.join(md))


if __name__ == '__main__':
    main()
