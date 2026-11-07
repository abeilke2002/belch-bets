"""Flatten raw Odds API snapshots -> data/odds_books.parquet (per book) and data/odds_lines.parquet
(one row per event + player, with early_* and close_* consensus columns)."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from config import BOOKS, DATA, MARKET, RAW


def american_to_prob(a):
    a = np.asarray(a, dtype=float)
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.where(a > 0, 100 / (a + 100), -a / (-a + 100))


def american_to_decimal(a):
    a = np.asarray(a, dtype=float)
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.where(a > 0, 1 + a / 100, 1 + 100 / -a)


def read_raw(raw_dir, market=MARKET):
    rows = []
    for f in sorted(Path(raw_dir).glob('*.json')):
        resp = json.loads(f.read_text())
        meta, data = resp.get('_meta', {}), resp.get('data')
        if not data:
            continue
        ev = meta.get('event', data)
        for bk in data.get('bookmakers', []):
            for mk in bk.get('markets', []):
                if mk['key'] != market:
                    continue
                for o in mk['outcomes']:
                    rows.append({'event_id': data['id'], 'snapshot': meta.get('snapshot'),
                                 'season': meta.get('season'), 'snapshot_ts': resp.get('timestamp'),
                                 'commence_time': data.get('commence_time', ev.get('commence_time')),
                                 'home_team': data.get('home_team'), 'away_team': data.get('away_team'),
                                 'book': bk['key'], 'player': o.get('description'),
                                 'side': o['name'], 'point': o.get('point'), 'price': o['price'],
                                 'link': o.get('link') or mk.get('link') or bk.get('link')})
    return pd.DataFrame(rows)


def book_lines(raw):
    keys = ['event_id', 'snapshot', 'season', 'snapshot_ts', 'commence_time', 'home_team',
            'away_team', 'book', 'player', 'point']
    wide = raw.pivot_table(index=keys, columns='side', values='price', aggfunc='first').reset_index()
    wide = wide.dropna(subset=['Over', 'Under']).rename(columns={'Over': 'over_price',
                                                                 'Under': 'under_price'})
    if 'link' in raw and raw['link'].notna().any():          # sportsbook bet-slip links (live pulls only)
        links = raw.dropna(subset=['link']).pivot_table(index=keys, columns='side', values='link', aggfunc='first')
        links = links.rename(columns={'Over': 'over_link', 'Under': 'under_link'}).reset_index()
        wide = wide.merge(links, on=keys, how='left')
    for c in ('over_link', 'under_link'):
        if c not in wide:
            wide[c] = None
    po, pu = american_to_prob(wide['over_price']), american_to_prob(wide['under_price'])
    wide['novig_over'] = po / (po + pu)
    wide['hold'] = po + pu - 1
    return wide


def consensus(books):
    """Consensus = the line most books post (ties -> closest to the median line)."""
    def agg(g):
        counts = g['point'].value_counts()
        med = g['point'].median()
        cand = counts[counts == counts.max()].index
        line = min(cand, key=lambda p: (abs(p - med), p))
        at = g[g['point'] == line]
        bo, bu = at.loc[at['over_price'].idxmax()], at.loc[at['under_price'].idxmax()]
        return pd.Series({'line': line, 'novig_over': at['novig_over'].median(),
                          'best_over_link': bo['over_link'], 'best_under_link': bu['under_link'],
                          'n_books': len(at), 'n_books_all': len(g),
                          'line_min': g['point'].min(), 'line_max': g['point'].max(),
                          'best_over_price': bo['over_price'], 'best_over_book': bo['book'],
                          'best_under_price': bu['under_price'], 'best_under_book': bu['book'],
                          'hold': at['hold'].median()})
    keys = ['event_id', 'snapshot', 'player']
    meta = books.groupby(keys)[['season', 'commence_time', 'home_team', 'away_team']].first()
    return meta.join(books.groupby(keys).apply(agg, include_groups=False)).reset_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw-dir', default=RAW)
    ap.add_argument('--out-dir', default=DATA)
    ap.add_argument('--market', default=MARKET, help='e.g. player_rebounds; output files get a matching suffix')
    args = ap.parse_args()
    out = Path(args.out_dir)
    sfx = '' if args.market == MARKET else '_' + args.market.replace('player_', '')

    raw = read_raw(args.raw_dir, args.market)
    if raw.empty:
        raise SystemExit('No props found in raw files.')
    raw = raw[raw['book'].isin(BOOKS)]              # only books you bet at (config.BOOKS)
    books = book_lines(raw)
    books.to_parquet(out / f'odds_books{sfx}.parquet', index=False)

    cons = consensus(books)
    meta_cols = ['season', 'commence_time', 'home_team', 'away_team']
    value_cols = [c for c in cons.columns if c not in meta_cols + ['event_id', 'snapshot', 'player']]
    early = cons[cons.snapshot == 'early'].set_index(['event_id', 'player'])
    close = cons[cons.snapshot == 'close'].set_index(['event_id', 'player'])
    lines = (early[value_cols].add_prefix('early_')
             .join(close[value_cols].add_prefix('close_'), how='outer'))
    meta = cons.groupby(['event_id', 'player'])[meta_cols].first()
    lines = meta.join(lines).reset_index()
    lines.to_parquet(out / f'odds_lines{sfx}.parquet', index=False)

    print(f'{len(books):,} book lines, {books.book.nunique()} books, '
          f'{books.event_id.nunique()} games')
    print(f'{len(lines):,} player-games | early line: {lines.early_line.notna().mean():.0%} | '
          f'close line: {lines.close_line.notna().mean():.0%} | both: '
          f'{(lines.early_line.notna() & lines.close_line.notna()).mean():.0%}')
    print(f'median hold at consensus line: {books.hold.median():.1%}')


if __name__ == '__main__':
    main()
