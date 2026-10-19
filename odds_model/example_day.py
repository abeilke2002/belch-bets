"""Walk through one past day exactly as the noon rule would have played it (out-of-sample for 2024-26).

    python example_day.py              # random 2025-26 day
    python example_day.py --seed 7     # another random day
    python example_day.py --date 2026-03-19

Rule: noon report, Questionable teammates at half; skip players on the report and back-to-backs; bet the
single highest edge if >= 2%, staked in proportion to edge (avg about 1u); the #2 pick is shown for tracking.
"""
import argparse

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from classifier import build_dataset, fit, predict_over
from config import DATA
from parse_odds import american_to_decimal, american_to_prob

F = ['logit_novig', 'gap', 'gapz']
TRAIN_FOR = {'2023-24': ['2024-25', '2025-26'], '2024-25': ['2023-24'], '2025-26': ['2023-24', '2024-25']}
AVG_TOP_EDGE = 0.043            # average edge of the walk-forward daily picks -> 1 unit


def stake_for(edge, gp=99):
    """Quarter units, 0.25u-1.5u; 1u max at 8%+ edges; 0.5u max until the player has 20 games."""
    u = float(np.clip(round(edge / AVG_TOP_EDGE * 4) / 4, 0.25, 1.5))
    u = min(u, 1.0) if edge >= 0.08 else u
    return min(u, 0.5) if gp < 20 else u


def book_table(p):
    """Every book's noon offer on the pick, scored against the one consensus probability."""
    books = pd.read_parquet(DATA / 'odds_books.parquet')
    b = books[(books['snapshot'] == 'early') & (books['event_id'] == p['event_id']) & (books['player'] == p['player'])].copy()
    over = p['side'] == 'OVER'
    prob = p['p_over'] if over else 1 - p['p_over']
    b['price'] = b['over_price'] if over else b['under_price']
    b['be'] = american_to_prob(b['price'])
    b['edge'] = np.where(b['point'] == p['line'], prob - b['be'], np.nan)
    b['note'] = np.where(b['point'] == p['line'], '', 'different line (not scored)')
    b = b.sort_values('edge', ascending=False)
    print(f"   by book ({p['side']} {p['line']}, model P({p['side'].lower()}) = {prob:.1%} for every book):")
    for r in b.itertuples():
        e = '' if np.isnan(r.edge) else f'edge {r.edge:+.1%}'
        print(f"      {r.book:15s} {r.point:5.1f}  {int(r.price):+5d}  break-even {r.be:.1%}  {e} {r.note}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, default=2026)
    ap.add_argument('--date')
    ap.add_argument('--season', default='2025-26')
    args = ap.parse_args()

    g = pd.read_parquet(DATA / 'player_games.parquet')
    teams = g.drop_duplicates('TEAM_ID').set_index('TEAM_ID')['teamName']
    rep = pd.read_parquet(DATA / 'noon_injuries.parquet')[['GAME_ID', 'PLAYER_ID', 'status']] \
        .drop_duplicates(['GAME_ID', 'PLAYER_ID'])
    d = build_dataset(DATA).drop(columns=['pred_points']).merge(
        pd.read_parquet(DATA / 'noon_projections_half.parquet')[['PLAYER_ID', 'GAME_ID', 'pred']],
        on=['PLAYER_ID', 'GAME_ID']).merge(rep, on=['GAME_ID', 'PLAYER_ID'], how='left')
    d = d.assign(gap=d['pred'] - d['line'], gapz=(d['pred'] - d['line']) / d['pred_sd'])

    day = pd.Timestamp(args.date) if args.date else pd.Timestamp(
        np.random.default_rng(args.seed).choice(sorted(d[d['season'] == args.season]['GAME_DATE'].unique())))
    x = d[d['GAME_DATE'] == day].copy()
    season = x['season'].iloc[0]
    tr = d[d['season'].isin(TRAIN_FOR[season])]
    x['p_over'] = predict_over(fit(tr), x)                     # market fixed + recency-weighted
    x['p_old'] = LogisticRegression(max_iter=2000).fit(tr[F], tr['over']).predict_proba(x[F])[:, 1]

    x['be_over'] = american_to_prob(x['early_best_over_price'])
    x['be_under'] = american_to_prob(x['early_best_under_price'])
    x['edge_over'], x['edge_under'] = x['p_over'] - x['be_over'], (1 - x['p_over']) - x['be_under']
    x['side'] = np.where(x['edge_over'] >= x['edge_under'], 'OVER', 'UNDER')
    x['edge'] = x[['edge_over', 'edge_under']].max(axis=1)
    x['old edge'] = np.where(x['side'] == 'OVER', x['p_old'] - x['be_over'], (1 - x['p_old']) - x['be_under'])
    old_side_over = (x['p_old'] - x['be_over']) >= ((1 - x['p_old']) - x['be_under'])
    x['old_best'] = np.maximum(x['p_old'] - x['be_over'], (1 - x['p_old']) - x['be_under'])
    x['filter'] = np.select([x['status'].isin(['Probable', 'Questionable', 'Doubtful']), x['rest_days'] == 1],
                            ['SKIP: ' + x['status'].fillna(''), 'SKIP: back-to-back'], 'ok')
    over = x['side'] == 'OVER'
    x['price'] = np.where(over, x['early_best_over_price'], x['early_best_under_price'])
    x['book'] = np.where(over, x['early_best_over_book'], x['early_best_under_book'])
    x['bet'] = [f'{s} {l} @ {int(p):+d} {b}' for s, l, p, b in zip(x['side'], x['line'], x['price'], x['book'])]
    x['won'] = np.where(over, x['points'] > x['line'], x['points'] < x['line'])
    x['matchup'] = x['TEAM_ID'].map(teams) + ' vs ' + x['OPP_ID'].map(teams)

    games = sorted({' vs '.join(sorted([a, b])) for a, b in zip(x['TEAM_ID'].map(teams), x['OPP_ID'].map(teams))})
    print(f"DAY: {day.date()} ({season}) | {len(games)} games | {len(x)} noon props at your four books | "
          f"{(x['filter'] == 'ok').sum()} eligible")
    print('games:', ', '.join(games))
    # Play column: what the daily rule does with each prop
    el_rank = x[x['filter'] == 'ok']['edge'].rank(ascending=False, method='first')
    x['play'] = np.select(
        [x['filter'] != 'ok', el_rank.reindex(x.index).eq(1) & (x['edge'] >= 0.02), x['edge'] < 0.02],
        [x['filter'].str.replace('SKIP: ', 'skip (') + ')',
         'BET ' + x['side'] + ' ' + pd.Series([f'{stake_for(e, n):g}u' for e, n in zip(x['edge'], x['gp'])], x.index),
         'pass (edge < 2%)'],
        'pass (not top pick)')
    cols = ['player', 'matchup', 'bet', 'early_novig_over', 'pred', 'gap', 'p_over', 'edge', 'old edge', 'play', 'points', 'close_line']
    top = x.sort_values('edge', ascending=False).head(10)[cols].rename(columns={
        'early_novig_over': 'mkt P(over)', 'pred': 'projection', 'p_over': 'model P(over)', 'points': 'actual',
        'close_line': 'close'})
    pd.set_option('display.width', 320)
    print('\nTOP 10 PROPS BY EDGE:')
    print(top.round(3).to_string(index=False))

    el = x[x['filter'] == 'ok'].sort_values('edge', ascending=False)
    for rank, label in [(0, 'PICK #1 (bet)'), (1, 'PICK #2 (track only)')]:
        if len(el) <= rank:
            break
        p = el.iloc[rank]
        if p['edge'] < 0.02:
            print(f"\n{label}: {p['player']} {p['bet']} | edge {p['edge']:+.1%} -> below 2%, NO BET")
            if rank == 0:
                book_table(p)
            continue
        stake = stake_for(p['edge'], p['gp']) if rank == 0 else 1.0
        units = stake * ((american_to_decimal(p['price']) - 1) if p['won'] else -1)
        mv = (p['close_line'] - p['line']) * (1 if p['side'] == 'OVER' else -1)
        clv = 'moved our way' if mv > 0 else 'unchanged' if mv == 0 else 'moved against us'
        print(f"\n{label}: {p['player']} {p['bet']} | model {max(p['p_over'], 1 - p['p_over']):.1%} vs break-even "
              f"{p['be_over'] if p['side'] == 'OVER' else p['be_under']:.1%} -> edge {p['edge']:+.1%}"
              + (f" -> stake {stake:g}u" if rank == 0 else ''))
        if rank == 0:
            book_table(p)
        if rank == 0:
            o = el.sort_values('old_best', ascending=False).iloc[0]
            same = o['player'] == p['player']
            print(f"   old model: this side's edge {p['old edge']:+.1%}; its own top pick was "
                  + ('the same' if same else f"{o['player']} ({o['old_best']:+.1%})"))
        print(f"   result: scored {int(p['points'])} -> {'WIN' if p['won'] else 'LOSS'} ({units:+.2f}u"
              f"{'' if rank == 0 else ' if bet at 1u'}) | close {p['close_line']} ({clv})")


if __name__ == '__main__':
    main()
