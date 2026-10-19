"""Score every book's own noon line instead of only the best price at the consensus line.

  current          market input = consensus no-vig; bet the best price among books AT the consensus line
  per book, own    market input = that book's own no-vig at its line; gap vs that book's line
  per book, anchor market input = consensus no-vig shifted to that book's line (k per point, from training
                   seasons); gap vs that book's line -> finds books out of line with the market
Same classifier weights (fit on consensus rows, walk-forward), same filters, 1 bet/day, edge >= 2%,
stakes scaled to edge. Writes reports/per_book_test.md.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from classifier import build_dataset, logit
from config import DATA, REPORTS
from parse_odds import american_to_decimal, american_to_prob

F = ['logit_novig', 'gap', 'gapz']
PLAN = [('2024-25', ['2023-24']), ('2025-26', ['2023-24', '2024-25']), ('2023-24', ['2024-25', '2025-26'])]


def per_point(train):
    tr = train[train['line'] % 1 == 0.5]
    return float((tr['points'] == tr['line'] - 0.5).mean())


def to_md(df):
    cols = [str(c) for c in df.columns]
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def pick_and_settle(c):
    """c: candidate bets with GAME_DATE, season, edge, side_over, line, points, price. 1/day, edge >= 2%."""
    c = c[c['edge'] >= 0.02].sort_values('edge', ascending=False).drop_duplicates('GAME_DATE')
    win = np.where(c['side_over'], c['points'] > c['line'], c['points'] < c['line'])
    stake = np.clip(np.round(c['edge'] / c['edge'].mean() * 4) / 4, 0.25, 1.5)
    units = np.where(win, american_to_decimal(c['price']) - 1, -1.0) * stake
    return c.assign(win=win, stake=stake, units=units)


def main():
    rep = pd.read_parquet(DATA / 'noon_injuries.parquet')[['GAME_ID', 'PLAYER_ID', 'status']] \
        .drop_duplicates(['GAME_ID', 'PLAYER_ID'])
    d = build_dataset(DATA).drop(columns=['pred_points']).merge(
        pd.read_parquet(DATA / 'noon_projections_half.parquet')[['PLAYER_ID', 'GAME_ID', 'pred']],
        on=['PLAYER_ID', 'GAME_ID']).merge(rep, on=['GAME_ID', 'PLAYER_ID'], how='left')
    d = d.assign(gap=d['pred'] - d['line'], gapz=(d['pred'] - d['line']) / d['pred_sd'])
    # classifier trains on every prop; the filters apply only to which props can be bet
    eligible = ~d['status'].isin(['Probable', 'Questionable', 'Doubtful']) & (d['rest_days'] != 1)

    books = pd.read_parquet(DATA / 'odds_books.parquet')
    books = books[books['snapshot'] == 'early'][['event_id', 'player', 'book', 'point', 'over_price', 'under_price',
                                                 'novig_over']]
    keys = d[['event_id', 'player', 'GAME_ID', 'PLAYER_ID', 'GAME_DATE', 'season', 'points', 'pred', 'pred_sd',
              'line', 'early_novig_over', 'early_best_over_price', 'early_best_under_price']]
    pb = books.merge(keys[eligible.values], on=['event_id', 'player'])

    results = {}
    for test, train in PLAN:
        tr = d[d['season'].isin(train)]
        lr = LogisticRegression(max_iter=2000).fit(tr[F], tr['over'])
        k = per_point(tr)

        # current: consensus line, best price among books at that line
        te = d[(d['season'] == test) & eligible].copy()
        te['p'] = lr.predict_proba(te[F])[:, 1]
        eo = te['p'] - american_to_prob(te['early_best_over_price'])
        eu = (1 - te['p']) - american_to_prob(te['early_best_under_price'])
        te['side_over'], te['edge'] = eo >= eu, np.maximum(eo, eu)
        te['price'] = np.where(te['side_over'], te['early_best_over_price'], te['early_best_under_price'])
        results.setdefault('current (consensus line, best price)', []).append(pick_and_settle(te))

        x = pb[pb['season'] == test].copy()
        x['gap'] = x['pred'] - x['point']
        x['gapz'] = x['gap'] / x['pred_sd']
        for name, market in [('per book, own no-vig', x['novig_over']),
                             ('per book, anchored on consensus', x['early_novig_over'] + k * (x['line'] - x['point']))]:
            y = x.assign(logit_novig=logit(market.clip(0.02, 0.98)))
            y['p'] = lr.predict_proba(y[F])[:, 1]
            eo = y['p'] - american_to_prob(y['over_price'])
            eu = (1 - y['p']) - american_to_prob(y['under_price'])
            y['side_over'], y['edge'] = eo >= eu, np.maximum(eo, eu)
            y['price'] = np.where(y['side_over'], y['over_price'], y['under_price'])
            y = y.assign(cons_line=y['line'], line=y['point'])
            results.setdefault(name, []).append(pick_and_settle(y))

    rows = []
    for name, parts in results.items():
        b = pd.concat(parts)
        s = pd.Series(b['units'].values, index=b['GAME_DATE'].values).sort_index()
        c = s.cumsum()
        per = ' / '.join(f"{b.loc[b['season'] == x, 'units'].sum():+.1f}" for x in ['2023-24', '2024-25', '2025-26'])
        off = (b['line'] != b['cons_line']).mean() if 'cons_line' in b else 0.0
        rows.append({'method': name, 'bets': len(b), 'win %': f"{b['win'].mean():.1%}",
                     'units risked': round(b['stake'].sum()), 'units won': f"{b['units'].sum():+.1f}",
                     'ROI': f"{b['units'].sum() / b['stake'].sum():+.1%}", '23-24 / 24-25 / 25-26': per,
                     'max drawdown': f'{(c - c.cummax()).min():.1f}', 'picks on an off-consensus line': f'{off:.0%}'})
    md = ['# Score each book\'s own line?\n', to_md(pd.DataFrame(rows)), '']
    (REPORTS / 'per_book_test.md').write_text('\n'.join(md))
    print('\n'.join(md))



if __name__ == '__main__':
    main()
