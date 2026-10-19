"""Where is the market weakest? Break the noon test seasons into segments and check, per segment:
  market:  over rate vs the market's no-vig P(over), and "always under" at the best noon price
  model:   the noon classifier's bets with edge >= MIN_EDGE in that segment (flat 1u)
Only segments positive in BOTH test seasons are worth trusting (many slices -> some look good by luck).
Writes reports/segments.md.
"""
import numpy as np
import pandas as pd

from config import DATA, REPORTS
from parse_odds import american_to_decimal
from strategy import settle

MIN_EDGE = 0.02
SEASONS = ['2024-25', '2025-26']


def segment_columns(t):
    tip_et = pd.to_datetime(t['commence_time'], utc=True).dt.tz_convert('America/New_York')
    month = t['GAME_DATE'].dt.month
    season_end = t.groupby('season')['GAME_DATE'].transform('max')
    return {
        'books posting the prop (noon)': t['early_n_books'].fillna(0).astype(int).clip(upper=4).astype(str),
        'line': pd.cut(t['line'], [0, 9.5, 14.5, 19.5, 24.5, 60],
                       labels=['under 10', '10-14.5', '15-19.5', '20-24.5', '25+']).astype(str),
        'rest': np.where(t['rest_days'] == 1, 'back-to-back', 'rested'),
        'tip time (ET)': np.where(tip_et.dt.hour >= 21, '9pm or later', 'before 9pm'),
        'part of season': np.select([month.isin([10, 11]), month.isin([12, 1, 2])],
                                    ['Oct-Nov', 'Dec-Feb'], 'Mar-Apr'),
        'last 7 days of season': np.where(t['GAME_DATE'] > season_end - pd.Timedelta(days=7), 'yes', 'no'),
        'starter': np.where(t['start_rate'].fillna(0) >= 0.5, 'starter', 'bench'),
        'own injury status (noon)': t['status'].fillna('not listed').replace({'Doubtful': 'Questionable'}),
    }


def market_row(x):
    price = x['early_best_under_price']
    win = x['points'] < x['line']
    profit = np.where(win, american_to_decimal(price) - 1, -1.0)
    return {'props': len(x), 'over rate': f"{x['over'].mean():.1%}",
            'market P(over)': f"{x['early_novig_over'].mean():.1%}",
            'always-under ROI': f'{profit.mean():+.1%}'}


def model_row(x):
    b = x[x['score'] >= MIN_EDGE]
    if len(b) < 20:
        return {'model bets': len(b)}
    win, profit = settle(b)
    by = {s: profit[(b['season'] == s).values].sum() for s in SEASONS}
    both = all(v > 0 for v in by.values())
    return {'model bets': len(b), 'model win %': f'{win.mean():.1%}', 'model ROI': f'{profit.mean():+.1%}',
            'units 24-25': f'{by[SEASONS[0]]:+.1f}', 'units 25-26': f'{by[SEASONS[1]]:+.1f}',
            'positive both seasons': 'YES' if both else ''}


def to_md(df):
    cols = [str(c) for c in df.columns]
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def main():
    t = pd.read_parquet(DATA / 'noon_backtest_scored.parquet')
    t = t[t['variant'] == 'noon injury report | gap only'].copy()
    t['score'] = t['edge']
    segs = segment_columns(t)

    md = ['# Where is the market weakest? (noon lines, 2024-25 + 2025-26)\n',
          f'Market columns use every prop; model columns use the noon classifier bets with edge >= {MIN_EDGE:.0%}, '
          'flat 1u at the best price among your four books.\n']
    rows = [{'segment': 'ALL', 'group': 'all', **market_row(t), **model_row(t)}]
    for name, col in segs.items():
        for grp in sorted(pd.unique(col)):
            x = t[col == grp]
            rows.append({'segment': name, 'group': grp, **market_row(x), **model_row(x)})
    res = pd.DataFrame(rows).fillna('')
    md += [to_md(res), '']
    (REPORTS / 'segments.md').write_text('\n'.join(md))
    print('\n'.join(md))


if __name__ == '__main__':
    main()
