"""Feature importance for the minutes and points models, measured on walk-forward test seasons.

    permutation: RMSE increase when the feature is shuffled in the test season (main ranking)
    SHAP share:  share of the mean |contribution| to predictions (LightGBM's built-in SHAP values)
    gain share:  LightGBM split gain (inflated for correlated features)
Writes reports/feature_importance.md and .csv.
"""
import numpy as np
import pandas as pd

from config import REPORTS
from regression import MINUTES_GROUPS, POINTS_GROUPS, fit, load_rows, minutes_for_season, selected

TEST = ['2023-24', '2024-25']
REPEATS = 3


def rmse(a, b):
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


def importance(df, features, target, groups, pred_min=None):
    rng = np.random.default_rng(0)
    rows, grows, tests = [], [], []
    for s in TEST:
        d = df if pred_min is None else df.assign(pred_minutes=pred_min[s])
        train, test = d[d['season'] < s], d[d['season'] == s]
        model = fit(train[features], train[target])
        X, y = test[features], test[target].values
        tests.append(X)
        base = rmse(model.predict(X), y)

        contrib = model.booster_.predict(X, pred_contrib=True)[:, :-1]      # drop bias column
        shap = np.abs(contrib).mean(0)
        gain = model.booster_.feature_importance('gain')
        for i, f in enumerate(features):
            inc = []
            for _ in range(REPEATS):
                Xp = X.copy()
                Xp[f] = rng.permutation(Xp[f].values)
                inc.append(rmse(model.predict(Xp), y) - base)
            rows.append({'season': s, 'feature': f, 'perm': np.mean(inc),
                         'shap': shap[i] / shap.sum(), 'gain': gain[i] / gain.sum()})
        for g, fs in groups.items():
            fs = [f for f in fs if f in features]
            if not fs:
                continue
            Xp = X.copy()
            idx = rng.permutation(len(Xp))
            Xp[fs] = Xp[fs].values[idx]                     # shuffle the group's rows together
            grows.append({'season': s, 'group': g, 'features': ', '.join(fs),
                          'perm': rmse(model.predict(Xp), y) - base})

    t = pd.DataFrame(rows).groupby('feature')[['perm', 'shap', 'gain']].mean()
    t['perm by season'] = pd.DataFrame(rows).pivot(index='feature', columns='season', values='perm') \
        .round(3).astype(str).agg(' / '.join, axis=1)
    corr = pd.concat(tests).corr().abs()
    np.fill_diagonal(corr.values, 0)
    t['most correlated with'] = [f'{corr[f].idxmax()} ({corr[f].max():.2f})' for f in t.index]
    t = t.sort_values('perm', ascending=False)
    t.insert(0, 'rank', range(1, len(t) + 1))
    g = pd.DataFrame(grows).groupby(['group', 'features'])['perm'].mean().reset_index() \
        .sort_values('perm', ascending=False)
    return t, g


def to_md(df):
    cols = [str(c) for c in df.columns]
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def fmt(t):
    t = t.reset_index()
    t['perm'] = t['perm'].map(lambda v: f'{v:+.3f}')
    t[['shap', 'gain']] = t[['shap', 'gain']].map(lambda v: f'{v:.1%}')
    return t.rename(columns={'perm': 'RMSE increase if shuffled', 'shap': 'SHAP share', 'gain': 'gain share',
                             'perm by season': 'by season (23-24 / 24-25)'})


def main():
    df = load_rows()
    min_feats, pts_feats = selected('minutes'), selected('points')

    print('minutes model...', flush=True)
    mt, mg = importance(df, min_feats, 'MINUTES', MINUTES_GROUPS)
    print('points model...', flush=True)
    pred_min = {s: minutes_for_season(df, s, min_feats) for s in TEST}
    pt, pg = importance(df, pts_feats, 'points', {**POINTS_GROUPS}, pred_min)

    md = ['# Feature importance (out-of-sample, test seasons 2023-24 and 2024-25)\n',
          '**RMSE increase if shuffled** is the main ranking: how much worse the predictions get when '
          "that feature's values are scrambled. Features with a highly correlated twin (right column) "
          'share credit, so each can look less important alone than its group does together.\n']
    for title, t, g, unit in [('Points model', pt, pg, 'points'), ('Minutes model', mt, mg, 'minutes')]:
        md += [f'## {title} (RMSE in {unit})\n', '### By feature\n', to_md(fmt(t)), '',
               '### By group (all features in the group shuffled together)\n',
               to_md(g.assign(perm=g['perm'].map(lambda v: f'{v:+.3f}'))
                     .rename(columns={'perm': 'RMSE increase if shuffled'})), '']
    (REPORTS / 'feature_importance.md').write_text('\n'.join(md))
    pd.concat([pt.assign(model='points'), mt.assign(model='minutes')]).to_csv(
        REPORTS / 'feature_importance.csv')

    for title, t, g in [('POINTS', pt, pg), ('MINUTES', mt, mg)]:
        print(f'\n{title} by feature'); print(fmt(t).drop(columns='by season (23-24 / 24-25)').to_string(index=False))
        print(f'\n{title} by group'); print(g.round(3).to_string(index=False))
    print('\nsaved reports/feature_importance.md and .csv')


if __name__ == '__main__':
    main()
