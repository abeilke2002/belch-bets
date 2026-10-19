"""Simulate betting the classifier's edges on the early lines; report ROI, calibration and CLV.

    python backtest.py --model lgbm --margin 0.02
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from config import DATA, REPORTS
from parse_odds import american_to_decimal, american_to_prob


def place_bets(df, pcol, margin):
    d = df.copy()
    d['p_over'] = d[pcol]
    d['edge_over'] = d['p_over'] - american_to_prob(d['early_best_over_price'])
    d['edge_under'] = (1 - d['p_over']) - american_to_prob(d['early_best_under_price'])
    d['side'] = np.where(d['edge_over'] >= d['edge_under'], 'over', 'under')
    return settle(d, d['side'], np.maximum(d['edge_over'], d['edge_under']), margin)


def settle(d, side, edge, margin=-np.inf):
    d = d.assign(side=side, edge=edge)
    d = d[d['edge'] > margin].copy()
    over = d['side'] == 'over'
    d['price'] = np.where(over, d['early_best_over_price'], d['early_best_under_price'])
    d['book'] = np.where(over, d['early_best_over_book'], d['early_best_under_book'])
    d['decimal'] = american_to_decimal(d['price'])
    d['p_side'] = np.where(over, d.get('p_over', np.nan), 1 - d.get('p_over', np.nan))
    d['win'] = np.where(over, d['points'] > d['line'], d['points'] < d['line'])
    d['profit'] = np.where(d['win'], d['decimal'] - 1, -1.0)
    # CLV: did the closing line move toward our side?
    d['clv_points'] = np.where(over, d['close_line'] - d['line'], d['line'] - d['close_line'])
    same = d['close_line'] == d['line']
    side_close = np.where(over, d['close_novig_over'], 1 - d['close_novig_over'])
    side_early = np.where(over, d['early_novig_over'], 1 - d['early_novig_over'])
    d['clv_prob'] = np.where(same, side_close - side_early, np.nan)
    d['beat_close'] = np.where(d['close_line'].isna(), np.nan,
                               (d['clv_points'] > 0) | (same & (d['clv_prob'] > 0)))
    return d


def kelly_sim(bets, fraction, cap=0.05, day_cap=0.25, start=100.0):
    """Stakes sized each day on the start-of-day bankroll (bets on a day are simultaneous).
    Each bet is capped at `cap`, and a day's total stake at `day_cap`, of the bankroll."""
    bank, path = start, []
    for _, day in bets.sort_values('GAME_DATE').groupby('GAME_DATE'):
        b = day['decimal'] - 1
        f = (fraction * (b * day['p_side'] - (1 - day['p_side'])) / b).clip(0, cap)
        if f.sum() > day_cap:
            f *= day_cap / f.sum()
        bank += (f * bank * day['profit']).sum()
        path.append(bank)
    path = np.array(path) if path else np.array([start])
    peak = np.maximum.accumulate(np.r_[start, path])
    return path[-1], ((np.r_[start, path] - peak) / peak).min()


def summarize(b, rng):
    if len(b) == 0:
        return {'bets': 0}
    boot = [b['profit'].sample(frac=1, replace=True, random_state=int(s)).mean()
            for s in rng.integers(0, 1e9, 1000)]
    clv = b.dropna(subset=['close_line'])
    return {'bets': len(b), 'win rate': b['win'].mean(), 'avg price': b['price'].median(),
            'ROI': b['profit'].mean(), 'ROI 95% CI': f"[{np.percentile(boot, 2.5):+.1%}, "
                                                    f"{np.percentile(boot, 97.5):+.1%}]",
            'units': b['profit'].sum(),
            'beat close': clv['beat_close'].astype(float).mean() if len(clv) else np.nan,
            'avg CLV pts': clv['clv_points'].mean() if len(clv) else np.nan}


def to_md(df):
    cols = [str(c) for c in df.columns]
    lines = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    lines += ['| ' + ' | '.join(str(v) for v in row) + ' |' for row in df.itertuples(index=False)]
    return '\n'.join(lines)


def fmt(df):
    out = df.copy()
    for c in ['win rate', 'ROI', 'beat close']:
        if c in out:
            out[c] = out[c].map(lambda v: '' if pd.isna(v) else f'{v:.1%}')
    for c in ['units', 'avg CLV pts']:
        if c in out:
            out[c] = out[c].map(lambda v: '' if pd.isna(v) else f'{v:+.2f}')
    return to_md(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', default=DATA, type=Path)
    ap.add_argument('--model', default='lgbm', choices=['lgbm', 'logreg', 'market_recal'])
    ap.add_argument('--margin', type=float, default=0.02, help='required edge over break-even')
    ap.add_argument('--kelly', type=float, default=0.25)
    args = ap.parse_args()
    rng = np.random.default_rng(0)

    df = pd.read_parquet(args.data_dir / 'classifier_preds.parquet')
    bets = place_bets(df, f'p_{args.model}', args.margin)
    md = [f'# Backtest: {args.model}, edge margin {args.margin:.0%}\n',
          f'Test rows: {len(df):,} player-games with an early line. Bets at the best early price '
          f'across books, settled on actual points; DNPs voided, pushes dropped.\n']

    rows = []
    for s, g in list(df.groupby('season')) + [('all', df)]:
        b = bets if s == 'all' else bets[bets['season'] == s]
        final, dd = kelly_sim(b, args.kelly)
        rows.append({'season': s, **summarize(b, rng),
                     f'{args.kelly:g} Kelly bankroll (100 start)': f'{final:,.0f}',
                     'max drawdown': f'{dd:.0%}'})
    md += ['## Model bets\n', fmt(pd.DataFrame(rows)), '']

    base = []
    for name, side in [('always under', np.full(len(df), 'under')),
                       ('always over', np.full(len(df), 'over')),
                       ('market favorite side', np.where(df['early_novig_over'] >= 0.5, 'over', 'under')),
                       ('random side', rng.choice(['over', 'under'], len(df)))]:
        base.append({'strategy': name, **summarize(settle(df, side, np.zeros(len(df))), rng)})
    md += ['## Baselines (bet every row, flat 1u)\n', fmt(pd.DataFrame(base)), '']

    df['p_model'] = df[f'p_{args.model}']
    df['bucket'] = pd.qcut(df['p_model'], 10, duplicates='drop')
    cal = df.groupby('bucket', observed=True).agg(n=('over', 'size'), predicted=('p_model', 'mean'),
                                                  market=('early_novig_over', 'mean'),
                                                  actual=('over', 'mean')).reset_index()
    cal['bucket'] = cal['bucket'].astype(str)
    md += ['## Calibration (all test rows, P(over) deciles)\n', to_md(cal.round(3)), '']

    def breakdown(col, title):
        t = pd.DataFrame([{col: k, **summarize(g, rng)} for k, g in bets.groupby(col, observed=True)])
        return [f'## By {title}\n', fmt(t), '']
    if len(bets):
        bets['edge bucket'] = pd.cut(bets['edge'], [args.margin, 0.04, 0.06, 0.10, 1]).astype(str)
        bets['line tier'] = pd.cut(bets['line'], [0, 10, 15, 20, 25, 60]).astype(str)
        for col, title in [('edge bucket', 'edge size'), ('line tier', 'line (player scoring tier)'),
                           ('side', 'side'), ('book', 'book')]:
            md += breakdown(col, title)

    tag = f'{args.model}_m{int(args.margin * 100):02d}'
    report = REPORTS / f'backtest_{tag}.md' if args.data_dir == DATA else args.data_dir / f'backtest_{tag}.md'
    report.write_text('\n'.join(md))
    bets.to_csv(report.with_suffix('.csv'), index=False)
    print('\n'.join(md[:8]))
    print(f'\nFull report: {report}')


if __name__ == '__main__':
    main()
