"""Past seasons for the rebounds and assists pages: site/seasons_{rebounds,assists}.json (same format as seasons.json).

    python build_history_stats.py          # seconds: uses the walk-forward projections stat_backtest.py saved

Same rule and seasons as build_history.py (points), so the home page compares like with like: every prop not on the
injury report or a back-to-back with an edge >= 2%, flat 1u, at the best noon price, nothing from April 1 on, nothing
on a team in its first 3 games after a player left it midseason. Rebounds take unders only (the backtest's overs lost).
Projections (stat_backtest.py --no-hindsight) are trained only on earlier seasons; the over/under weights for a season
only on the seasons before it (2024-25: 2023-24; 2025-26: 2023-24 and 2024-25).
"""
import json

import numpy as np
import pandas as pd

import build_history as BH
import stat_backtest as SB
from config import DATA, ROOT
from parse_odds import american_to_prob

PLAN = {'2025-26': ['2023-24', '2024-25'], '2024-25': ['2023-24']}
MARKETS = {'rebounds': ('reb', ['dlogit'], ('UNDER',)), 'assists': ('ast', ['gap', 'gapz'], ('OVER', 'UNDER'))}
MIN_EDGE, STAKE = 0.02, 1.0


def season_bets(d, test, train, cols, sides, market, left):
    f, _ = SB.fit_offset(d[d['season'].isin(train)], cols)
    te = d[d['season'] == test].copy()
    te['p'] = f(te)
    eo = te['p'] - american_to_prob(te['early_best_over_price'])
    eu = (1 - te['p']) - american_to_prob(te['early_best_under_price'])
    if 'OVER' not in sides:
        eo = eo * 0 - 1
    if 'UNDER' not in sides:
        eu = eu * 0 - 1
    te['over_side'], te['edge'] = eo >= eu, np.maximum(eo, eu)
    april_on = pd.to_datetime(te['GAME_DATE']).dt.month.isin([4, 5, 6])
    gone = pd.Series([k in left for k in zip(te['GAME_ID'], te['teamName'])], index=te.index)
    b = te[~te['status'].isin(SB.ON_REPORT) & (te['rest_days'] != 1) & (te['edge'] >= MIN_EDGE) & ~april_on & ~gone]
    b = b.sort_values(['GAME_DATE', 'edge'], ascending=[True, False])
    over = b['over_side'].values
    price = np.where(over, b['early_best_over_price'], b['early_best_under_price']).astype(int)
    win = np.where(over, b['over'] == 1, b['over'] == 0)
    profit = np.where(price > 0, price / 100, 100 / -price)
    team, home = b['teamName'].map(BH.TEAM_ABBR).fillna(b['teamName']).values, b['home_team'].map(BH.abbr).values
    return pd.DataFrame({
        'date': pd.to_datetime(b['GAME_DATE']).dt.date.astype(str).values, 'player': b['player_name'].values,
        'team': team, 'opponent': np.where(team == home, b['away_team'].map(BH.abbr).values, home), 'market': market,
        'side': np.where(over, 'OVER', 'UNDER'), 'line': b['early_line'].values, 'price': price,
        'book': [BH.BOOK_NAMES.get(x, x) for x in np.where(over, b['early_best_over_book'], b['early_best_under_book'])],
        'edge': np.round(b['edge'].values, 4), 'stake': STAKE, 'result': np.where(win, 'win', 'loss'),
        'points': b[SB.STATS[market]].values, 'units': np.round(np.where(win, profit, -1.0) * STAKE, 2)})


def main():
    left = BH.left_behind_rows()
    names = pd.read_parquet(DATA / 'player_games.parquet', columns=['GAME_ID', 'PLAYER_ID', 'player_name', 'teamName'])
    for market, (key, cols, sides) in MARKETS.items():
        d = SB.props(market, pd.read_pickle(DATA / f'stat_preds_{market}_nohind.pkl'), key)
        d = d.merge(names, on=['GAME_ID', 'PLAYER_ID'], how='left')
        seasons = []
        for test, train in PLAN.items():
            bets = season_bets(d, test, train, cols, sides, market, left)
            u = bets['units'].sum()
            print(f'{market} {test}: {len(bets)} bets, {(bets.result == "win").mean():.1%}, {u:+.1f}u ({u / len(bets):+.1%})')
            seasons.append({'season': test, 'kind': 'backtest', 'bets': json.loads(bets.to_json(orient='records')),
                            'note': f'Backtest, every eligible {market} prop with a 2%+ edge at 1u'
                                    f'{" (unders only)" if sides == ("UNDER",) else ""}: projections trained only on earlier '
                                    f'seasons, over/under model trained on {" and ".join(train)}.'})
        (ROOT / 'site' / f'seasons_{market}.json').write_text(json.dumps({'seasons': seasons}, separators=(',', ':')))


if __name__ == '__main__':
    main()
