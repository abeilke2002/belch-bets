"""Out-of-sample check of the betting rule on 2023-24, a season not used to choose it.

Projections for 2023-24 are walk-forward (models trained on 2018-23 only). The classifier's three weights
(market log-odds, projection gap, scaled gap) are fit on 2024-25 + 2025-26 and applied to 2023-24.
Rules and filters were fixed before running this. Writes reports/validate_2023.md.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from classifier import build_dataset
from config import DATA, REPORTS
from parse_odds import american_to_prob
from strategy import evaluate

F = ['logit_novig', 'gap', 'gapz']
ON_REPORT = {'Probable', 'Questionable', 'Doubtful'}


def to_md(df):
    cols = [str(c) for c in df.columns]
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def scored(d, train_seasons, test_season):
    x = d.assign(gap=d['pred_noon'] - d['line'], gapz=(d['pred_noon'] - d['line']) / d['pred_sd'])
    tr, te = x[x['season'].isin(train_seasons)], x[x['season'] == test_season].copy()
    lr = LogisticRegression(max_iter=2000).fit(tr[F], tr['over'])
    te['p'] = lr.predict_proba(te[F])[:, 1]
    eo = te['p'] - american_to_prob(te['early_best_over_price'])
    eu = (1 - te['p']) - american_to_prob(te['early_best_under_price'])
    te['side_over'], te['score'] = eo >= eu, np.maximum(eo, eu)
    return te, np.round(lr.coef_[0], 3)


def rules(t, season_label):
    filt = ~t['status'].isin(ON_REPORT) & (t['rest_days'] != 1)
    role = t['line'].between(10, 14.5)
    out = []
    for name, mask in [('no filters', pd.Series(True, index=t.index)), ('filters', filt),
                       ('filters + lines 10-14.5', filt & role)]:
        r = evaluate(t[mask], ks=(1, 3, 999), min_scores=(0.04,), label=f'{season_label} | {name}')
        out.append(r)
    r = pd.concat(out, ignore_index=True)
    r['max bets/day'] = r['max bets/day'].replace(999, 'all')
    return r


def main():
    d = build_dataset(DATA).merge(pd.read_parquet(DATA / 'noon_projections.parquet'), on=['PLAYER_ID', 'GAME_ID'])
    status = pd.read_parquet(DATA / 'noon_injuries.parquet')[['GAME_ID', 'PLAYER_ID', 'status']]
    d = d.merge(status.drop_duplicates(['GAME_ID', 'PLAYER_ID']), on=['GAME_ID', 'PLAYER_ID'], how='left')

    t23, coef = scored(d, ['2024-25', '2025-26'], '2023-24')
    cols = ['strategy', 'max bets/day', 'bets', 'days with a bet', 'win %', 'ROI', 'units 2023-24',
            'max drawdown (u)', 'worst month (u)', 'line moved our way / against']
    res = rules(t23, '2023-24 (fresh season)')
    md = ['# Fresh-season check: 2023-24\n',
          f'Classifier weights fit on 2024-25 + 2025-26 [market, gap, scaled gap] = {coef}. Edge >= 4%, '
          'flat 1u at the best noon price among your four books. Filters: skip players listed Probable/'
          'Questionable/Doubtful on the noon report, skip back-to-backs.\n',
          to_md(res[[c for c in cols if c in res]]), '']
    (REPORTS / 'validate_2023.md').write_text('\n'.join(md))
    print('\n'.join(md))


if __name__ == '__main__':
    main()
