"""Score a betting strategy the way it would actually be played: each day, take at most K bets, the ones
with the highest score, and only if they clear a minimum score. Days with nothing qualifying are skipped.

Results are in flat units: 1 unit risked per bet, a win pays the odds (+0.91u at -110), a loss is -1u.

Input frame needs: GAME_DATE, season, GAME_ID, score (higher = better bet), side_over (bool), line, points,
early_best_over_price, early_best_under_price, and optionally close_line for CLV.
"""
import numpy as np
import pandas as pd

from parse_odds import american_to_decimal
from selection import clustered_ci


def daily_top_k(t, k, min_score, one_per_game=True):
    c = t[t['score'] > min_score].sort_values('score', ascending=False)
    if one_per_game:                      # don't stack several props from the same game
        c = c.drop_duplicates('GAME_ID')
    return c.groupby('GAME_DATE', group_keys=False).head(k)


def settle(b):
    over = b['side_over'].values
    price = np.where(over, b['early_best_over_price'], b['early_best_under_price'])
    win = np.where(over, b['points'] > b['line'], b['points'] < b['line'])
    return win, np.where(win, american_to_decimal(price) - 1, -1.0)


def units_profile(b, profit):
    """Flat 1-unit stakes: units by season, max drawdown, worst calendar month."""
    p = pd.Series(profit, index=b.index)
    order = b['GAME_DATE'].sort_values(kind='stable').index
    curve = p.loc[order].cumsum()
    drawdown = (curve - curve.cummax()).min()
    by_season = p.groupby(b['season']).sum()
    by_month = p.groupby(b['GAME_DATE'].dt.to_period('M')).sum()
    return by_season, drawdown, by_month.min(), by_month.idxmin()


def evaluate(t, ks=(1, 3, 5), min_scores=(0.0, 0.02, 0.04), label=''):
    rows = []
    n_days = t['GAME_DATE'].nunique()
    for k in ks:
        for ms in min_scores:
            b = daily_top_k(t, k, ms)
            if len(b) < 30:
                continue
            win, profit = settle(b)
            m, lo, hi = clustered_ci(profit, b['GAME_DATE'].values)
            by_season, dd, worst, worst_month = units_profile(b, profit)
            row = {'strategy': label, 'max bets/day': k, 'min score': ms, 'bets': len(b),
                   'days with a bet': f"{b['GAME_DATE'].nunique()}/{n_days}", 'win %': f'{win.mean():.1%}',
                   'ROI': f'{m:+.1%} [{lo:+.1%}, {hi:+.1%}]'}
            for season, u in by_season.items():
                row[f'units {season}'] = f'{u:+.1f}'
            row.update({'units total': f'{profit.sum():+.1f}', 'max drawdown (u)': f'{dd:.1f}',
                        'worst month (u)': f'{worst:+.1f} ({worst_month})'})
            if 'close_line' in b:
                cl = b.dropna(subset=['close_line'])
                clv = np.where(cl['side_over'], cl['close_line'] - cl['line'], cl['line'] - cl['close_line'])
                row['line moved our way / against'] = f'{(clv > 0).mean():.0%} / {(clv < 0).mean():.0%}'
            rows.append(row)
    return pd.DataFrame(rows)
