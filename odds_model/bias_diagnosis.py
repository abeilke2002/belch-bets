"""Where does the star-out over-prediction come from, and does damping the injury adjustment fix it?

Walk-forward on 2023-24 + 2024-25 with the production feature set. For each test season, a damping
factor alpha (prediction = no-injury prediction + alpha * injury adjustment) is fit on the TRAINING
seasons only, using leave-one-season-out predictions, then applied to the test season.
Writes reports/bias_diagnosis.md.
"""
import numpy as np
import pandas as pd

from build_features import add_redistribution
from config import REPORTS
from injury_analysis import OUT_COLS, star_out_games
from regression import fit, load_rows, selected
from selection import clustered_ci

TEST = ['2023-24', '2024-25']


def predict_pair(train, test, min_f, pts_f):
    """Predictions with tonight's real absences and with nobody out (history unchanged)."""
    train = train.copy()
    train['pred_minutes'] = np.nan
    for t in train['season'].unique():
        if (train.season != t).any():
            m = fit(train.loc[train.season != t, min_f], train.loc[train.season != t, 'MINUTES'])
            train.loc[train.season == t, 'pred_minutes'] = m.predict(train.loc[train.season == t, min_f])
    min_model, pts_model = fit(train[min_f], train['MINUTES']), None
    pts_model = fit(train[pts_f], train['points'])
    cf = test.copy()
    cf[OUT_COLS] = 0
    cf = add_redistribution(cf)
    test, cf = test.copy(), cf.assign(pred_minutes=min_model.predict(cf[min_f]))
    test['pred_minutes'] = min_model.predict(test[min_f])
    return pts_model.predict(test[pts_f]), pts_model.predict(cf[pts_f])


def damp(adj, a, c):
    """Concave damping: small adjustments kept almost whole, large ones shrunk."""
    return a * adj / (1 + c * np.abs(adj))


def fit_alpha(train, min_f, pts_f):
    """Linear factor alpha and concave (a, c) from leave-one-season-out predictions in the training seasons."""
    adjs, resids = [], []
    for t in train['season'].unique():
        tr, va = train[train.season != t], train[train.season == t]
        if tr['season'].nunique() < 2:
            continue
        p, pcf = predict_pair(tr, va, min_f, pts_f)
        adjs.append(p - pcf)
        resids.append(va['points'].values - pcf)
    adj, resid = np.concatenate(adjs), np.concatenate(resids)
    alpha = (adj * resid).sum() / (adj * adj).sum()
    from scipy.optimize import curve_fit
    (a, c), _ = curve_fit(damp, adj, resid, p0=[1.0, 0.05], bounds=([0, 0], [2, 2]))
    return alpha, a, c


def to_md(df):
    cols = [str(c) for c in df.columns]
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def main():
    df = load_rows().merge(star_out_games(), on=['GAME_ID', 'TEAM_ID'], how='left')
    df['star_out'] = df['star_out_ppg'].notna()
    min_f, pts_f = selected('minutes'), selected('points')

    parts = []
    for s in TEST:
        train, test = df[df['season'] < s], df[df['season'] == s].copy()
        test['pred'], test['pred_cf'] = predict_pair(train, test, min_f, pts_f)
        alpha, a, c = fit_alpha(train, min_f, pts_f)
        test['alpha'] = alpha
        test['pred_damped'] = test['pred_cf'] + alpha * (test['pred'] - test['pred_cf'])
        test['pred_concave'] = test['pred_cf'] + damp(test['pred'] - test['pred_cf'], a, c)
        test['concave'] = f'a={a:.2f}, c={c:.3f}'
        parts.append(test)
        print(f'{s}: alpha = {alpha:.3f} | concave a = {a:.3f}, c = {c:.3f}', flush=True)
    res = pd.concat(parts)
    res['adj'] = res['pred'] - res['pred_cf']
    res['resid'] = res['points'] - res['pred']
    star = res[res['star_out']].copy()

    md = ['# Star-out bias diagnosis (walk-forward, 2023-24 + 2024-25)\n',
          'bias = prediction - actual (positive = over-predicting). CI clustered by game date.\n']

    def bias_row(name, d, col='pred'):
        m, lo, hi = clustered_ci((d[col] - d['points']).values, d['GAME_DATE'].values)
        return {'slice': name, 'n': len(d), 'bias': f'{m:+.2f} [{lo:+.2f}, {hi:+.2f}]',
                'mean injury adjustment': f"{d['adj'].mean():+.2f}"}

    # 1. Is it star-out specific, and is it every season?
    rows = [bias_row('all games', res), bias_row('no star out', res[~res.star_out]), bias_row('star out', star)]
    rows += [bias_row(f'star out, {s}', star[star.season == s]) for s in TEST]
    rows += [bias_row(f'no star out, {s}', res[~res.star_out & (res.season == s)]) for s in TEST]
    md += ['## 1. Where is the bias?\n', to_md(pd.DataFrame(rows)), '']

    # 2. By size of the model's injury adjustment
    star['adj bucket'] = pd.cut(star['adj'], [-np.inf, 0, 1, 2, 4, np.inf]).astype(str)
    rows = [bias_row(f'adjustment {k}', g) for k, g in star.groupby('adj bucket')]
    md += ['## 2. By size of the injury adjustment (star-out games)\n', to_md(pd.DataFrame(rows)), '']

    # 3. Fresh vs long-running absences
    frac_new = (star['out_fga'] - star['out_fga_season_avg'].fillna(0)) / star['out_fga'].where(star['out_fga'] > 0)
    star['absence'] = np.select([frac_new >= 0.75, frac_new >= 0.25], ['fresh (mostly new)', 'mixed'],
                                'long-running (mostly baked in)')
    rows = [bias_row(k, g) for k, g in star.groupby('absence')]
    md += ['## 3. Fresh vs long-running absences\n', to_md(pd.DataFrame(rows)), '']

    # 4. Damping fix
    rows = []
    for name, d in [('all games', res), ('star out', star), ('no star out', res[~res.star_out])]:
        for col, label in [('pred', 'current'), ('pred_damped', 'flat damping'), ('pred_concave', 'concave damping')]:
            se = (d[col] - d['points']) ** 2
            diff = ((d['pred'] - d['points']) ** 2 - se).values
            m, lo, hi = clustered_ci(diff, d['GAME_DATE'].values)
            rows.append({'slice': name, 'version': label, 'RMSE': round(float(np.sqrt(se.mean())), 4),
                         'bias': round(float((d[col] - d['points']).mean()), 3),
                         'MSE reduction vs current': '' if col == 'pred' else f'{m:+.3f} [{lo:+.3f}, {hi:+.3f}]'})
    alphas = ', '.join(f"{s}: alpha {res.loc[res.season == s, 'alpha'].iloc[0]:.2f}, concave "
                       f"{res.loc[res.season == s, 'concave'].iloc[0]}" for s in TEST)
    # bias by adjustment size after each fix
    star['adj bucket'] = pd.cut(star['adj'], [-np.inf, 0, 1, 2, 4, np.inf]).astype(str)
    by = star.groupby('adj bucket').apply(lambda g: pd.Series({
        'n': len(g), 'current': round((g['pred'] - g['points']).mean(), 2),
        'flat damping': round((g['pred_damped'] - g['points']).mean(), 2),
        'concave damping': round((g['pred_concave'] - g['points']).mean(), 2)}), include_groups=False).reset_index()
    md += [f'## 4. Damping the injury adjustment (alpha fit on training seasons only: {alphas})\n',
           to_md(pd.DataFrame(rows).fillna('')), '',
           '### Bias by adjustment size after each fix (star-out games)\n', to_md(by), '']

    (REPORTS / 'bias_diagnosis.md').write_text('\n'.join(md))
    print('\n'.join(md))


if __name__ == '__main__':
    main()
