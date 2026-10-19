"""Choose the minutes and points model features by walk-forward backward elimination.

Test seasons 2023-24 and 2024-25 (each predicted by models trained only on earlier seasons).
Writes data/selected_features.json (read by regression.py) and reports/feature_study.md.
"""
import json

import numpy as np
import pandas as pd

from config import REPORTS
from regression import (MINUTES_GROUPS, POINTS_GROUPS, SELECTED, fit, load_rows, minutes_for_season)
from selection import backward_eliminate, clustered_ci

TEST = ['2023-24', '2024-25']
ORIGINAL_18 = ['pts_season', 'pts_5', 'pts_3', 'fga_season', 'fga_5', 'fga_3', 'fta_season', 'fta_5',
               'min_season', 'min_5', 'min_3', 'pts_std', 'gp', 'rest_days', 'prev_season_ppg',
               'out_ppg', 'n_out', 'is_home']


def walk_forward(df, features, target, extra=None):
    """Squared errors on the test seasons, each from a model trained on earlier seasons only."""
    losses, dates = [], []
    for s in TEST:
        d = df if extra is None else df.assign(pred_minutes=extra[s])
        train, test = d[(d['season'] < s) & d[features].notna().any(axis=1)], d[d['season'] == s]
        pred = fit(train[features], train[target]).predict(test[features])
        losses.append((pred - test[target].values) ** 2)
        dates.append(test['GAME_DATE'].values)
    return np.concatenate(losses), np.concatenate(dates)


def to_md(df):
    cols = [str(c) for c in df.columns]
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def main():
    df = load_rows()
    md = ['# Feature study (walk-forward, test seasons 2023-24 + 2024-25)\n',
          'A feature group is kept only if removing it raises out-of-sample squared error with a 95% CI '
          '(clustered by game date) entirely above zero. Removed one group per round, weakest first.\n']

    # 1. Minutes model
    print('== minutes model ==')
    min_kept, min_rounds = backward_eliminate(
        MINUTES_GROUPS, lambda f: walk_forward(df, f, 'MINUTES'))
    min_feats = [f for fs in min_kept.values() for f in fs]

    base5 = np.concatenate([((df.loc[df.season == s, 'min_5'].fillna(df.loc[df.season == s, 'min_season'])
                              - df.loc[df.season == s, 'MINUTES']) ** 2).values for s in TEST])
    model_loss, dates = walk_forward(df, min_feats, 'MINUTES')
    m, lo, hi = clustered_ci(base5 - model_loss, dates)
    md += ['## Minutes model\n',
           f'Kept groups: **{", ".join(min_kept)}**\n',
           f'| | RMSE minutes |\n|---|---|\n| Last-5 average | {np.sqrt(base5.mean()):.3f} |\n'
           f'| Minutes model | {np.sqrt(model_loss.mean()):.3f} |\n',
           f'MSE reduction vs last-5: {m:.2f} (95% CI [{lo:.2f}, {hi:.2f}])\n',
           to_md(min_rounds.round(4)), '']

    # 2. Points model, with leave-one-season-out predicted minutes from the kept minutes features
    print('== points model ==')
    pred_min = {s: minutes_for_season(df, s, min_feats) for s in TEST}
    pts_kept, pts_rounds = backward_eliminate(
        POINTS_GROUPS, lambda f: walk_forward(df, f, 'points', pred_min))
    pts_feats = [f for fs in pts_kept.values() for f in fs]

    comp = []
    for name, feats in [('original 18 features', ORIGINAL_18),
                        ('all candidates', [f for fs in POINTS_GROUPS.values() for f in fs]),
                        ('selected', pts_feats)]:
        loss, dates = walk_forward(df, feats, 'points', pred_min)
        comp.append((name, len(feats), loss))
    base = comp[0][2]
    rows = []
    for name, n, loss in comp:
        m, lo, hi = clustered_ci(base - loss, dates)
        rows.append({'feature set': name, 'n features': n, 'RMSE points': round(np.sqrt(loss.mean()), 4),
                     'MSE reduction vs original': f'{m:+.3f} [{lo:+.3f}, {hi:+.3f}]'})
    season_avg = np.concatenate([((df.loc[df.season == s, 'pts_season'] - df.loc[df.season == s, 'points'])
                                  ** 2).values for s in TEST])
    rows.append({'feature set': 'season average (no model)', 'n features': 1,
                 'RMSE points': round(np.sqrt(season_avg.mean()), 4), 'MSE reduction vs original': ''})
    md += ['## Points model\n', f'Kept groups: **{", ".join(pts_kept)}**\n', to_md(pd.DataFrame(rows)), '',
           '### Elimination rounds\n', to_md(pts_rounds.round(4)), '']

    SELECTED.write_text(json.dumps({'minutes': min_feats, 'points': pts_feats,
                                    'minutes_groups': list(min_kept), 'points_groups': list(pts_kept)}, indent=2))
    (REPORTS / 'feature_study.md').write_text('\n'.join(md))
    print(pd.DataFrame(rows).to_string(index=False))
    print(f'\nminutes features ({len(min_feats)}): {min_feats}\npoints features ({len(pts_feats)}): {pts_feats}')
    print(f'saved {SELECTED.name} and reports/feature_study.md')


if __name__ == '__main__':
    main()
