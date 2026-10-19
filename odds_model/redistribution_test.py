"""Does the shot-redistribution feature fix the under-reaction to injuries? Walk-forward, 2023-24 + 2024-25.

Variants of the points model (minutes model unchanged):
  A current selected features            B  A + redistribution
  C  B with monotone (+) constraints on the expected-extra features
  D  A + usage-freed-up (out_fga, out_fga_share), for reference
Writes reports/redistribution_test.md.
"""
import lightgbm as lgb
import numpy as np
import pandas as pd

from build_features import add_redistribution
from config import REPORTS
from injury_analysis import OUT_COLS, star_out_games
from regression import PARAMS, fit, load_rows, selected
from selection import clustered_ci

TEST = ['2023-24', '2024-25']
REDIST = ['usage_share', 'exp_extra_fga', 'exp_extra_pts']
NEW = ['usage_share', 'exp_extra_fga_new', 'exp_extra_pts_new', 'exp_extra_pts_recent']


def variants():
    base = selected('points')
    return {'A current': (base, None),
            'B + redistribution': (base + REDIST, None),
            'C + redistribution (monotone)': (base + REDIST, {'exp_extra_fga': 1, 'exp_extra_pts': 1}),
            'D + usage freed up': (base + ['out_fga', 'out_fga_share'], None),
            'E + NEW-absence redistribution': (base + NEW, None),
            'F + NEW-absence redistribution (monotone)': (base + NEW, {'exp_extra_pts_new': 1, 'exp_extra_fga_new': 1})}


def fit_points(X, y, features, mono):
    params = dict(PARAMS)
    if mono:
        params['monotone_constraints'] = [mono.get(f, 0) for f in features]
    return lgb.LGBMRegressor(**params).fit(X[features], y)


def run(df):
    min_f = selected('minutes')
    out = []
    for s in TEST:
        train, test = df[df['season'] < s].copy(), df[df['season'] == s].copy()
        train['pred_minutes'] = np.nan
        for t in train['season'].unique():
            m = fit(train.loc[train.season != t, min_f], train.loc[train.season != t, 'MINUTES'])
            train.loc[train.season == t, 'pred_minutes'] = m.predict(train.loc[train.season == t, min_f])
        min_model = fit(train[min_f], train['MINUTES'])
        cf = test.copy()
        cf[OUT_COLS] = 0
        cf = add_redistribution(cf)        # nobody out tonight (history of past absences unchanged)
        test['pred_minutes'] = min_model.predict(test[min_f])
        cf['pred_minutes'] = min_model.predict(cf[min_f])
        for name, (feats, mono) in variants().items():
            model = fit_points(train, train['points'], feats, mono)
            test[f'pred|{name}'] = model.predict(test[feats])
            test[f'cf|{name}'] = model.predict(cf[feats])
        out.append(test)
        print(f'{s}: done', flush=True)
    return pd.concat(out)


def to_md(df):
    cols = [str(c) for c in df.columns]
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def main():
    df = load_rows().merge(star_out_games(), on=['GAME_ID', 'TEAM_ID'], how='left')
    df['star_out'] = df['star_out_ppg'].notna()
    res = run(df)
    res['team_rank'] = res.groupby(['GAME_ID', 'TEAM_ID'])['pts_season'].rank(ascending=False, method='first')
    res['segment'] = np.select([res['team_rank'] == 1, res['pts_season'] >= 15, res['pts_season'] >= 8],
                               ['top remaining scorer', 'other 15+ ppg scorers', '8-15 ppg'], '<8 ppg')
    names = list(variants())
    subsets = {'all games': res, 'star out (all teammates)': res[res.star_out],
               'star out: top remaining scorer': res[res.star_out & (res.segment == 'top remaining scorer')],
               'star out: other 15+ scorers': res[res.star_out & (res.segment == 'other 15+ ppg scorers')],
               'star out: 8-15 ppg': res[res.star_out & (res.segment == '8-15 ppg')],
               'star out: <8 ppg': res[res.star_out & (res.segment == '<8 ppg')]}

    rows, moves = [], []
    for sub, d in subsets.items():
        y = d['points'].values
        base_se = (d[f'pred|{names[0]}'].values - y) ** 2
        for n in names:
            se = (d[f'pred|{n}'].values - y) ** 2
            m, lo, hi = clustered_ci(base_se - se, d['GAME_DATE'].values)
            rows.append({'subset': sub, 'n': len(d), 'variant': n, 'RMSE': round(np.sqrt(se.mean()), 4),
                         'bias': round((d[f'pred|{n}'] - d['points']).mean(), 3),
                         'MSE reduction vs A': '' if n == names[0] else f'{m:+.3f} [{lo:+.3f}, {hi:+.3f}]'})
            if sub != 'all games':
                adj = (d[f'pred|{n}'] - d[f'cf|{n}']).mean()
                upl = (d['points'] - d[f'cf|{n}']).mean()
                moves.append({'subset': sub, 'variant': n, 'model adjustment': f'{adj:+.2f}',
                              'actual uplift': f'{upl:+.2f}', 'share of uplift captured': f'{adj / upl:.0%}'})

    md = ['# Redistribution feature test (walk-forward, 2023-24 + 2024-25)\n',
          'MSE reduction vs A: positive = better than the current model; 95% CI clustered by game date.\n',
          '## Accuracy\n', to_md(pd.DataFrame(rows)), '',
          '## Does it move the right amount when a 15+ ppg teammate is out?\n', to_md(pd.DataFrame(moves)), '']
    (REPORTS / 'redistribution_test.md').write_text('\n'.join(md))
    print('\n'.join(md))


if __name__ == '__main__':
    main()
