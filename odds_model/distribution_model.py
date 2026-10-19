"""Full points distribution per player-game, priced without the odds (Whizard-style origination).

Points ~ Negative Binomial with mean = the noon projection and a dispersion r learned on earlier
seasons by projection level and starter role (MLE). P(over line) = P(points >= floor(line) + 1).
Two strategies, each scored day by day (top-K, flat units):
  origination   bet when P_dist(side) beats the break-even of the best price
  blended       logistic regression on the market's no-vig log-odds + the distribution's log-odds
Walk-forward: dispersion and blend fit on seasons before the test season only.
Writes reports/distribution_model.md.
"""
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize_scalar
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

from classifier import build_dataset, logit
from config import DATA, REPORTS
from parse_odds import american_to_prob
from strategy import evaluate

SEASONS = ['2023-24', '2024-25', '2025-26']
MEAN_BINS = [0, 6, 10, 14, 18, 23, 60]


def nb_logpmf(k, mu, r):
    p = r / (r + mu)
    return stats.nbinom.logpmf(k, r, p)


def fit_dispersion(train):
    """MLE dispersion r per (projection bin, starter) cell; larger r = less spread."""
    table = {}
    for (b, st), g in train.groupby(['mu_bin', 'starter'], observed=True):
        res = minimize_scalar(lambda lr: -nb_logpmf(g['points'].values, g['mu'].values, np.exp(lr)).sum(),
                              bounds=(-2, 6), method='bounded')
        table[(b, st)] = float(np.exp(res.x))
    return table


def p_over(mu, r, line):
    p = r / (r + mu)
    return stats.nbinom.sf(np.floor(line), r, p)        # P(points >= floor(line)+1) = P(points > line)


def to_md(df):
    cols = [str(c) for c in df.columns]
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def main():
    d = build_dataset(DATA).merge(pd.read_parquet(DATA / 'noon_projections.parquet'), on=['PLAYER_ID', 'GAME_ID'])
    d['mu'] = d['pred_noon'].clip(lower=0.5)
    d['mu_bin'] = pd.cut(d['mu'], MEAN_BINS)
    d['starter'] = (d['start_rate'].fillna(0) >= 0.5).astype(int)

    parts, ll_rows, disp_rows = [], [], []
    for s in SEASONS[1:]:
        tr, te = d[d['season'] < s].copy(), d[d['season'] == s].copy()
        table = fit_dispersion(tr)
        disp_rows += [{'fit for': s, 'projection': str(b), 'starter': st, 'r': round(r, 2)} for (b, st), r in table.items()]
        for x in (tr, te):
            x['r'] = [table.get((b, st), np.median(list(table.values()))) for b, st in zip(x['mu_bin'], x['starter'])]
            x['p_raw'] = p_over(x['mu'].values, x['r'].values, x['line'].values).clip(0.01, 0.99)
        # Raw NB probabilities lean under (lines sit near the median, our projection is a mean) and are too
        # extreme; map them to observed over rates on the training seasons only.
        iso = IsotonicRegression(y_min=0.02, y_max=0.98, out_of_bounds='clip').fit(tr['p_raw'], tr['over'])
        for x in (tr, te):
            x['p_dist'] = iso.predict(x['p_raw']).clip(0.02, 0.98)
            x['logit_dist'] = logit(x['p_dist'])
        blend = LogisticRegression(max_iter=2000).fit(tr[['logit_novig', 'logit_dist']], tr['over'])
        te['p_blend'] = blend.predict_proba(te[['logit_novig', 'logit_dist']])[:, 1]
        for name, col in [('market (no-vig)', 'early_novig_over'), ('distribution, raw', 'p_raw'),
                          ('distribution, calibrated', 'p_dist'),
                          ('blend: market + distribution', 'p_blend')]:
            ll_rows.append({'season': s, 'model': name, 'log loss': round(log_loss(te['over'], te[col]), 4),
                            'mean P(over)': round(te[col].mean(), 3)})
        te['blend_coefs'] = str(np.round(blend.coef_[0], 2))
        parts.append(te)
    t = pd.concat(parts)

    # Calibration of the pure distribution: predicted vs actual over rate
    t['p_bucket'] = pd.cut(t['p_dist'], [0, .44, .47, .49, .51, .53, .56, 1])
    cal = t.groupby('p_bucket', observed=True).agg(n=('over', 'size'), predicted=('p_dist', 'mean'),
                                                   market=('early_novig_over', 'mean'), actual=('over', 'mean'))
    cal = cal.round(3).reset_index().assign(p_bucket=lambda x: x['p_bucket'].astype(str))

    results = []
    for name, col in [('origination (distribution vs price)', 'p_dist'), ('blend (market + distribution)', 'p_blend')]:
        x = t.copy()
        eo = x[col] - american_to_prob(x['early_best_over_price'])
        eu = (1 - x[col]) - american_to_prob(x['early_best_under_price'])
        x['side_over'], x['score'] = eo >= eu, np.maximum(eo, eu)
        results.append(evaluate(x, ks=(1, 3, 5, 999), min_scores=(0.0, 0.02, 0.04, 0.06), label=name))
    bets = pd.concat(results, ignore_index=True)
    bets['max bets/day'] = bets['max bets/day'].replace(999, 'all')
    cols = ['strategy', 'max bets/day', 'min score', 'bets', 'win %', 'ROI', 'units 2024-25', 'units 2025-26',
            'units total', 'max drawdown (u)', 'line moved our way / against']

    md = ['# Points distribution model (no odds in the number)\n',
          'Negative binomial around the noon projection; dispersion fit on earlier seasons only.\n',
          '## Log loss on the test seasons (market = 0.6921)\n', to_md(pd.DataFrame(ll_rows)), '',
          f"Blend coefficients [market, distribution]: {', '.join(t.groupby('season')['blend_coefs'].first())}\n",
          '## Calibration of the distribution alone (test seasons)\n', to_md(cal), '',
          '## Betting (flat 1u, best noon price among your four books)\n', to_md(bets[cols]), '',
          '## Fitted dispersion r (larger = tighter)\n', to_md(pd.DataFrame(disp_rows)), '']
    (REPORTS / 'distribution_model.md').write_text('\n'.join(md))
    print('\n'.join(md[:8]))
    print(to_md(bets[cols]))


if __name__ == '__main__':
    main()
