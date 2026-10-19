"""Can the classifier be made less overconfident? Five versions, walk-forward on 2023-26 noon props.

  current       logistic regression on market log-odds, gap, scaled gap (as now)
  market fixed  market log-odds enters with weight exactly 1; only the projection terms are learned
  shrunk        current, but its move away from the market is scaled by alpha < 1, alpha learned from
                out-of-fold predictions inside the training seasons
  isotonic      current, then an isotonic calibration map learned from out-of-fold predictions
  recent-weighted  current, with each older training season counted at half the weight of the next
Scored on calibration (top 10% and top 1% by edge), log loss vs the market, and the betting rule.
Writes reports/calibration_test.md.
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.model_selection import GroupKFold

from classifier import build_dataset
from config import DATA, REPORTS
from parse_odds import american_to_decimal, american_to_prob

F = ['logit_novig', 'gap', 'gapz']
PLAN = [('2024-25', ['2023-24']), ('2025-26', ['2023-24', '2024-25']), ('2023-24', ['2024-25', '2025-26'])]
sig = lambda z: 1 / (1 + np.exp(-z))


def fit_lr(tr, w=None):
    lr = LogisticRegression(max_iter=3000).fit(tr[F], tr['over'], sample_weight=w)
    return lambda x: lr.decision_function(x[F])


def season_weights(tr):
    order = sorted(tr['season'].unique())
    return 0.5 ** tr['season'].map(lambda s: len(order) - 1 - order.index(s)).values


def fit_market_fixed(tr, w=None):
    X = tr[['gap', 'gapz']].values; off = tr['logit_novig'].values; y = tr['over'].values
    w = np.ones(len(tr)) if w is None else w
    def nll(b):
        p = np.clip(sig(off + b[0] + X @ b[1:]), 1e-6, 1 - 1e-6)
        return -(w * (y * np.log(p) + (1 - y) * np.log(1 - p))).sum() / w.sum()
    b = minimize(nll, np.zeros(3), method='BFGS').x
    return lambda x: x['logit_novig'].values + b[0] + x[['gap', 'gapz']].values @ b[1:]


def oof_logit(tr):
    """Out-of-fold current-model log-odds inside the training seasons (folds grouped by game date)."""
    z = np.zeros(len(tr))
    for a, b in GroupKFold(5).split(tr, groups=tr['GAME_DATE']):
        z[b] = fit_lr(tr.iloc[a])(tr.iloc[b])
    return z


def variants(tr):
    out = {'current': fit_lr(tr), 'market fixed': fit_market_fixed(tr)}
    base = out['current']
    z_oof, m_oof, y = oof_logit(tr), tr['logit_novig'].values, tr['over'].values
    def nll(a):
        p = np.clip(sig(m_oof + a * (z_oof - m_oof)), 1e-6, 1 - 1e-6)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()
    alpha = minimize_scalar(nll, bounds=(0, 1.5), method='bounded').x
    out['shrunk'] = lambda x, a=alpha: x['logit_novig'].values + a * (base(x) - x['logit_novig'].values)
    iso = IsotonicRegression(y_min=0.02, y_max=0.98, out_of_bounds='clip').fit(sig(z_oof), y)
    out['isotonic'] = lambda x: np.log(np.clip(iso.predict(sig(base(x))), 1e-4, 1 - 1e-4) /
                                       np.clip(1 - iso.predict(sig(base(x))), 1e-4, 1))
    out['recent-weighted'] = fit_lr(tr, w=season_weights(tr))
    out['market fixed + recent-weighted'] = fit_market_fixed(tr, w=season_weights(tr))
    return out, alpha


def to_md(df):
    cols = [str(c) for c in df.columns]
    o = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(o + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def main():
    rep = pd.read_parquet(DATA / 'noon_injuries.parquet')[['GAME_ID', 'PLAYER_ID', 'status']] \
        .drop_duplicates(['GAME_ID', 'PLAYER_ID'])
    d = build_dataset(DATA).drop(columns=['pred_points']).merge(
        pd.read_parquet(DATA / 'noon_projections_half.parquet')[['PLAYER_ID', 'GAME_ID', 'pred']],
        on=['PLAYER_ID', 'GAME_ID']).merge(rep, on=['GAME_ID', 'PLAYER_ID'], how='left')
    d = d.assign(gap=d['pred'] - d['line'], gapz=(d['pred'] - d['line']) / d['pred_sd'])

    preds, alphas = {}, []
    for test, train in PLAN:
        tr, te = d[d['season'].isin(train)].reset_index(drop=True), d[d['season'] == test].copy()
        models, a = variants(tr)
        alphas.append(f'{test}: {a:.2f}')
        for name, f in models.items():
            preds.setdefault(name, []).append(te.assign(p=sig(f(te))))

    rows = []
    for name, parts in preds.items():
        t = pd.concat(parts)
        eo = t['p'] - american_to_prob(t['early_best_over_price'])
        eu = (1 - t['p']) - american_to_prob(t['early_best_under_price'])
        t['side_over'], t['edge'] = eo >= eu, np.maximum(eo, eu)
        t['p_side'] = np.where(t['side_over'], t['p'], 1 - t['p'])
        price = np.where(t['side_over'], t['early_best_over_price'], t['early_best_under_price'])
        t['price'] = price
        t['win'] = np.where(t['side_over'], t['points'] > t['line'], t['points'] < t['line'])
        gain = np.mean([(log_loss(x['over'], x['early_novig_over']) - log_loss(x['over'], x['p'])) * 1e4
                        for _, x in t.groupby('season')])
        s = t.sort_values('edge', ascending=False)
        top10, top1 = s.head(len(s) // 10), s.head(len(s) // 100)

        # betting rule: filters, 1/day, edge >= 2%, stakes scaled to edge (avg 1u)
        el = t[~t['status'].isin(['Probable', 'Questionable', 'Doubtful']) & (t['rest_days'] != 1)]
        b = el.sort_values('edge', ascending=False).drop_duplicates('GAME_DATE')
        b = b[b['edge'] >= 0.02]
        stake = np.clip(np.round(b['edge'] / b['edge'].mean() * 4) / 4, 0.25, 1.5) if len(b) else b['edge']
        units = np.where(b['win'], american_to_decimal(b['price']) - 1, -1.0) * stake
        per = ' / '.join(f"{units[(b['season'] == x).values].sum():+.1f}" for x in ['2023-24', '2024-25', '2025-26'])
        rows.append({'version': name, 'beats market (log loss x1e-4)': f'{gain:+.1f}',
                     'top 10%: predicted / actual': f"{top10['p_side'].mean():.1%} / {top10['win'].mean():.1%}",
                     'top 1%: predicted / actual': f"{top1['p_side'].mean():.1%} / {top1['win'].mean():.1%}",
                     'daily picks: predicted / actual': f"{b['p_side'].mean():.1%} / {b['win'].mean():.1%}",
                     'bets': len(b), 'units': f'{units.sum():+.1f}', '23-24 / 24-25 / 25-26': per})
    res = pd.DataFrame(rows)
    md = ['# Classifier calibration test\n', f'Shrink factor alpha by test season: {", ".join(alphas)}\n', to_md(res), '']
    (REPORTS / 'calibration_test.md').write_text('\n'.join(md))
    print('\n'.join(md))


if __name__ == '__main__':
    main()
