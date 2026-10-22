"""Past seasons for the site's History tab: site/seasons.json (copied to the published site by daily_pipeline).

    python build_history.py

2025-26: the day-by-day replay of the live pipeline (data/replay/bet_log.csv), the site's own rules and stakes.
2024-25: the out-of-sample noon backtest (data/noon_backtest_scored.parquet, noon injury report, gap-only
classifier): each day's biggest edge if it clears 2%, flat 1u, DNPs void. The live season comes from picks.json.
Past seasons don't change, so this only needs rerunning if the replay or backtest is rebuilt.
"""
import json

import numpy as np
import pandas as pd

from config import DATA, ROOT

TEAM_ABBR = {'Hawks': 'ATL', 'Celtics': 'BOS', 'Nets': 'BKN', 'Hornets': 'CHA', 'Bulls': 'CHI', 'Cavaliers': 'CLE',
             'Mavericks': 'DAL', 'Nuggets': 'DEN', 'Pistons': 'DET', 'Warriors': 'GSW', 'Rockets': 'HOU', 'Pacers': 'IND',
             'Clippers': 'LAC', 'Lakers': 'LAL', 'Grizzlies': 'MEM', 'Heat': 'MIA', 'Bucks': 'MIL', 'Timberwolves': 'MIN',
             'Pelicans': 'NOP', 'Knicks': 'NYK', 'Thunder': 'OKC', 'Magic': 'ORL', '76ers': 'PHI', 'Suns': 'PHX',
             'Trail Blazers': 'POR', 'Kings': 'SAC', 'Spurs': 'SAS', 'Raptors': 'TOR', 'Jazz': 'UTA', 'Wizards': 'WAS'}
BOOK_NAMES = {'draftkings': 'DraftKings', 'fanduel': 'FanDuel', 'betmgm': 'BetMGM', 'williamhill_us': 'Caesars'}
COLS = ['date', 'player', 'team', 'opponent', 'side', 'line', 'price', 'book', 'stake', 'result', 'points', 'units']
abbr = lambda full: next((a for nick, a in TEAM_ABBR.items() if str(full).endswith(nick)), str(full))


def replay_2025_26():
    b = pd.read_csv(DATA / 'replay' / 'bet_log.csv')
    return b[COLS]


def backtest_2024_25():
    d = pd.read_parquet(DATA / 'noon_backtest_scored.parquet')
    d = d[(d['variant'] == 'noon injury report | gap only') & (d['season'] == '2024-25') & (d['edge'] >= 0.02)].copy()
    d['date'] = pd.to_datetime(d['commence_time']).dt.tz_convert('America/New_York').dt.date.astype(str)
    d = d.sort_values('edge', ascending=False).groupby('date').head(1).sort_values('date')
    over = d['side_over'].astype(bool)
    price = np.where(over, d['early_best_over_price'], d['early_best_under_price']).astype(int)
    bk = np.where(over, d['early_best_over_book'], d['early_best_under_book'])
    win = np.where(over, d['points'] > d['line'], d['points'] < d['line'])
    result = np.where(~d['played'].astype(bool), 'void', np.where(d['points'] == d['line'], 'push', np.where(win, 'win', 'loss')))
    profit = np.where(price > 0, price / 100, 100 / -price)
    home = d['home_team'].map(abbr).values
    team = d['teamName'].map(TEAM_ABBR).fillna(d['teamName']).values
    return pd.DataFrame({
        'date': d['date'].values, 'player': d['player_name'].values, 'team': team,
        'opponent': np.where(team == home, d['away_team'].map(abbr).values, home),
        'side': np.where(over, 'OVER', 'UNDER'), 'line': d['line'].values, 'price': price,
        'book': [BOOK_NAMES.get(x, x) for x in bk], 'stake': 1.0, 'result': result,
        'points': np.where(d['played'].astype(bool), d['points'], np.nan),
        'units': np.round(np.where(result == 'win', profit, np.where(result == 'loss', -1.0, 0.0)), 2)})


def main():
    seasons = [
        {'season': '2025-26', 'kind': 'replay',
         'note': "Replay: the site's own code run day by day on 2025-26, same rules and stake sizes. Its over/under "
                 'model was fit on data through April 2026, so it had seen this season.',
         'bets': replay_2025_26()},
        {'season': '2024-25', 'kind': 'backtest',
         'note': "Backtest: models trained only on earlier seasons, noon injury report, the day's biggest edge if "
                 "it cleared 2%, flat 1u stakes (the site's stake sizing didn't exist yet).",
         'bets': backtest_2024_25()},
    ]
    for s in seasons:
        s['bets'] = json.loads(s['bets'].to_json(orient='records'))
        n, u = len(s['bets']), sum(b['units'] or 0 for b in s['bets'])
        print(f"{s['season']}: {n} plays, {u:+.2f}u")
    (ROOT / 'site' / 'seasons.json').write_text(json.dumps({'seasons': seasons}, separators=(',', ':')))


if __name__ == '__main__':
    main()
