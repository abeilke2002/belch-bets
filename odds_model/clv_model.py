"""Predict how each prop moves from noon to tip, and bet the biggest predicted moves at noon.

Target ("move", in points of line): the market's change in value toward the over between the noon and
close consensus, combining the line change and the price change:
    move = (close_line - noon_line) + (close_noVig_over - noon_noVig_over) / k
where k is the probability per point of line (P(points lands on the integer a half-point line
crosses), measured from training data). +1.0 = like the line rising a full point.
Inputs are all known at noon. Walk-forward by season. Writes reports/clv_model.md.

    python clv_model.py [--proj pred_noon.parquet]   # projections to use for the gap feature
"""
import argparse

import lightgbm as lgb
import numpy as np
import pandas as pd

from classifier import build_dataset
from config import DATA, REPORTS
from parse_odds import american_to_decimal, american_to_prob
from selection import clustered_ci

SEASONS = ['2023-24', '2024-25', '2025-26']
FEATURES = ['skew', 'price_tilt', 'book_up', 'book_down', 'n_books', 'hold', 'gap', 'gapz', 'form5', 'form_season',
            'line', 'hours_to_tip', 'min_trend', 'q_ppg', 'own_probable', 'own_questionable']
# out_ppg deliberately excluded: the stored version uses who actually sat (hindsight). The noon-report
# version of teammates-out enters through --injuries instead.
PARAMS = dict(n_estimators=400, learning_rate=0.02, num_leaves=15, min_child_samples=300, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, verbose=-1, random_state=0)


def per_point(train):
    """k: probability that points equal the integer just below a .5 line, i.e. the mass one point of line moves."""
    tr = train[train['line'] % 1 == 0.5]
    return float((tr['points'] == tr['line'] - 0.5).mean())


def build(proj_path=None):
    d = build_dataset(DATA)
    if proj_path:
        d = d.drop(columns=['pred_points']).merge(
            pd.read_parquet(proj_path).rename(columns={'pred_noon': 'pred_points'}), on=['PLAYER_ID', 'GAME_ID'])
    d = d.dropna(subset=['close_line', 'close_novig_over'])
    d['skew'] = d['early_novig_over'] - 0.5
    d['price_tilt'] = american_to_prob(d['early_best_over_price']) - american_to_prob(d['early_best_under_price'])
    d['book_up'] = d['early_line_max'] - d['line']
    d['book_down'] = d['line'] - d['early_line_min']
    d['gap'] = d['pred_points'] - d['line']
    d['gapz'] = d['gap'] / d['pred_sd']
    d['form5'] = d['pts_5'] - d['line']
    d['form_season'] = d['pts_season'] - d['line']
    tip = pd.to_datetime(d['commence_time'], utc=True)
    d['hours_to_tip'] = (tip - tip.dt.tz_convert('America/New_York').dt.normalize().dt.tz_convert('UTC')
                         - pd.Timedelta(hours=12)).dt.total_seconds() / 3600
    for c in ['q_ppg', 'own_probable', 'own_questionable']:
        if c not in d:
            d[c] = np.nan                                   # filled once the injury reports are joined
    return d


def to_md(df):
    cols = [str(c) for c in df.columns]
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--proj', help='parquet with PLAYER_ID, GAME_ID, pred_noon (noon-knowable projections)')
    ap.add_argument('--injuries', help='parquet with PLAYER_ID, GAME_ID, q_ppg, own_probable, own_questionable')
    args = ap.parse_args()
    d = build(args.proj)
    if args.injuries:
        d = d.drop(columns=['q_ppg', 'own_probable', 'own_questionable']).merge(
            pd.read_parquet(args.injuries), on=['PLAYER_ID', 'GAME_ID'], how='left')

    parts, fit_rows = [], []
    for s in SEASONS[1:]:
        tr, te = d[d.season < s].copy(), d[d.season == s].copy()
        k = per_point(tr)
        for x in (tr, te):
            x['move'] = (x['close_line'] - x['line']) + (x['close_novig_over'] - x['early_novig_over']) / k
        model = lgb.LGBMRegressor(**PARAMS).fit(tr[FEATURES], tr['move'])
        te['pred_move'] = model.predict(te[FEATURES])
        corr = np.corrcoef(te['pred_move'], te['move'])[0, 1]
        hit = (np.sign(te['pred_move']) == np.sign(te['move']))[te['move'] != 0].mean()
        fit_rows.append({'test season': s, 'k (prob per point)': round(k, 3), 'n': len(te),
                         'corr(predicted, actual move)': round(corr, 3),
                         'direction right when line moved': f'{hit:.1%}',
                         'actual |move| (mean)': round(te['move'].abs().mean(), 2)})
        parts.append(te)
        imp = pd.Series(model.booster_.feature_importance('gain'), FEATURES)
    t = pd.concat(parts)

    bets = []
    for thr in [0.25, 0.5, 0.75, 1.0]:
        b = t[t['pred_move'].abs() >= thr]
        if len(b) < 30:
            continue
        over = (b['pred_move'] > 0).values
        price = np.where(over, b['early_best_over_price'], b['early_best_under_price'])
        win = np.where(over, b['points'] > b['line'], b['points'] < b['line'])
        profit = np.where(win, american_to_decimal(price) - 1, -1.0)
        m, lo, hi = clustered_ci(profit, b['GAME_DATE'].values)
        clv = np.where(over, b['move'], -b['move'])
        by_season = ' / '.join(f"{profit[(b.season == s).values].mean():+.1%}" for s in SEASONS[1:])
        bets.append({'bet when |predicted move| >=': thr, 'bets': len(b), 'win %': f'{win.mean():.1%}',
                     'ROI': f'{m:+.1%} [{lo:+.1%}, {hi:+.1%}]', 'ROI 24-25 / 25-26': by_season,
                     'realized CLV (pts)': f'{clv.mean():+.2f}', 'market moved our way': f'{(clv > 0).mean():.0%}'})

    md = ['# Line-movement (CLV) model: noon -> close\n',
          'Walk-forward: each season predicted from earlier seasons only. Bets placed at the best noon price '
          'among your four books, on the side the line is predicted to move toward.\n',
          '## How well it predicts the move\n', to_md(pd.DataFrame(fit_rows)), '',
          '## Betting the biggest predicted moves\n', to_md(pd.DataFrame(bets)), '',
          '## What drives the prediction (gain share, last model)\n',
          to_md((imp / imp.sum()).sort_values(ascending=False).round(3).reset_index()
                .rename(columns={'index': 'feature', 0: 'share'})), '']
    (REPORTS / 'clv_model.md').write_text('\n'.join(md))
    print('\n'.join(md))


if __name__ == '__main__':
    main()
