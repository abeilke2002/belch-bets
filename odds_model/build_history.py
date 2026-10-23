"""Past seasons for the site's History tab: site/seasons.json (copied to the published site by daily_pipeline).

    python build_history.py

Out-of-sample backtest of the current method (calibration_test.py's "market fixed + recent-weighted" classifier):
each season is predicted by a classifier trained only on earlier seasons, on noon lines and the noon injury report.
The site's rule each day: skip players on the injury report or a back-to-back, bet the biggest edge if it clears 2%,
stake = edge / 3.2% (rounded to 0.25u, 0.25-1.5u, max 1u above an 8% edge, max 0.5u before 20 games played).
The live season comes from picks.json. Rerun if the projections or the classifier are rebuilt.
"""
import json

import numpy as np
import pandas as pd

import calibration_test as ct
from config import DATA, ROOT
from parse_odds import american_to_prob

TEAM_ABBR = {'Hawks': 'ATL', 'Celtics': 'BOS', 'Nets': 'BKN', 'Hornets': 'CHA', 'Bulls': 'CHI', 'Cavaliers': 'CLE',
             'Mavericks': 'DAL', 'Nuggets': 'DEN', 'Pistons': 'DET', 'Warriors': 'GSW', 'Rockets': 'HOU', 'Pacers': 'IND',
             'Clippers': 'LAC', 'Lakers': 'LAL', 'Grizzlies': 'MEM', 'Heat': 'MIA', 'Bucks': 'MIL', 'Timberwolves': 'MIN',
             'Pelicans': 'NOP', 'Knicks': 'NYK', 'Thunder': 'OKC', 'Magic': 'ORL', '76ers': 'PHI', 'Suns': 'PHX',
             'Trail Blazers': 'POR', 'Kings': 'SAC', 'Spurs': 'SAS', 'Raptors': 'TOR', 'Jazz': 'UTA', 'Wizards': 'WAS'}
BOOK_NAMES = {'draftkings': 'DraftKings', 'fanduel': 'FanDuel', 'betmgm': 'BetMGM', 'williamhill_us': 'Caesars'}
PLAN = [('2024-25', ['2023-24']), ('2025-26', ['2023-24', '2024-25'])]
AVG_EDGE = 0.0323                                   # the site's stake scale (over_model.pkl avg_top_edge)
abbr = lambda full: next((a for nick, a in TEAM_ABBR.items() if str(full).endswith(nick)), str(full))


def dataset():
    """Noon props with the noon projection and injury status, as calibration_test.py builds them."""
    rep = pd.read_parquet(DATA / 'noon_injuries.parquet')[['GAME_ID', 'PLAYER_ID', 'status']] \
        .drop_duplicates(['GAME_ID', 'PLAYER_ID'])
    d = ct.build_dataset(DATA).drop(columns=['pred_points']).merge(
        pd.read_parquet(DATA / 'noon_projections_half.parquet')[['PLAYER_ID', 'GAME_ID', 'pred']],
        on=['PLAYER_ID', 'GAME_ID']).merge(rep, on=['GAME_ID', 'PLAYER_ID'], how='left')
    return d.assign(gap=d['pred'] - d['line'], gapz=(d['pred'] - d['line']) / d['pred_sd'])


def site_stake(edge, gp):
    u = np.clip(np.round(edge / AVG_EDGE * 4) / 4, 0.25, 1.5)
    u = np.where(edge >= 0.08, np.minimum(u, 1), u)
    return np.where(gp < 20, np.minimum(u, 0.5), u)


def season_bets(d, test, train):
    tr, te = d[d['season'].isin(train)].reset_index(drop=True), d[d['season'] == test].copy()
    te['p'] = ct.sig(ct.fit_market_fixed(tr, w=ct.season_weights(tr))(te))
    eo = te['p'] - american_to_prob(te['early_best_over_price'])
    eu = (1 - te['p']) - american_to_prob(te['early_best_under_price'])
    te['over_side'], te['edge'] = eo >= eu, np.maximum(eo, eu)
    el = te[~te['status'].isin(['Probable', 'Questionable', 'Doubtful']) & (te['rest_days'] != 1)]
    b = el.sort_values('edge', ascending=False).drop_duplicates('GAME_DATE')
    b = b[b['edge'] >= 0.02].sort_values('GAME_DATE')
    over = b['over_side'].values
    price = np.where(over, b['early_best_over_price'], b['early_best_under_price']).astype(int)
    win = np.where(over, b['points'] > b['line'], b['points'] < b['line'])
    stake = site_stake(b['edge'].values, b['gp'].values)
    profit = np.where(price > 0, price / 100, 100 / -price)
    team = b['teamName'].map(TEAM_ABBR).fillna(b['teamName']).values
    home = b['home_team'].map(abbr).values
    return pd.DataFrame({
        'date': pd.to_datetime(b['GAME_DATE']).dt.date.astype(str).values, 'player': b['player_name'].values,
        'team': team, 'opponent': np.where(team == home, b['away_team'].map(abbr).values, home),
        'side': np.where(over, 'OVER', 'UNDER'), 'line': b['line'].values, 'price': price,
        'book': [BOOK_NAMES.get(x, x) for x in np.where(over, b['early_best_over_book'], b['early_best_under_book'])],
        'stake': stake, 'result': np.where(win, 'win', 'loss'), 'points': b['points'].values,
        'units': np.round(np.where(win, profit, -1.0) * stake, 2)})


def main():
    d = dataset()
    seasons = []
    for test, train in reversed(PLAN):
        bets = season_bets(d, test, train)
        print(f'{test}: {len(bets)} plays, {bets["units"].sum():+.2f}u on {bets["stake"].sum():.1f}u risked')
        seasons.append({'season': test, 'kind': 'backtest', 'bets': json.loads(bets.to_json(orient='records')),
                        'note': f'Backtest, out of sample: the current method with a model trained only on '
                                f'{" and ".join(train)}, noon lines and injury report, the site\'s pick and stake rules.'})
    (ROOT / 'site' / 'seasons.json').write_text(json.dumps({'seasons': seasons}, separators=(',', ':')))


if __name__ == '__main__':
    main()
