"""Past seasons for the site's History tab: site/seasons.json (copied to the published site by daily_pipeline).

    python build_history.py            # about 5 minutes: rebuilds the noon projections from current data

Out-of-sample backtest of the site's rule: every prop not on the injury report or a back-to-back with an edge
>= 2%, flat 1u, at the best noon price. Projections ('half' injury policy, damping) and the classifier (market
fixed + recent-weighted) are both trained only on earlier seasons. 2023-24 is left out: it has no earlier lines,
so its classifier would have to be trained on later seasons. The live season comes from picks.json.
SPREAD: the same backtest retrained with 10 LightGBM seeds (scratch robustness run, 2026-10-23); the History
tab shows seed 0, the production setting, and quotes the 10-seed average and range next to it.
"""
import json

import numpy as np
import pandas as pd

import calibration_test as ct
import q_policy_test as qp
from build_features import add_redistribution
from config import DATA, ROOT
from damping import damp, fit_damping, predict_pair
from noon_backtest import season_averages
from parse_odds import american_to_prob
from regression import fit, load_rows, selected

TEAM_ABBR = {'Hawks': 'ATL', 'Celtics': 'BOS', 'Nets': 'BKN', 'Hornets': 'CHA', 'Bulls': 'CHI', 'Cavaliers': 'CLE',
             'Mavericks': 'DAL', 'Nuggets': 'DEN', 'Pistons': 'DET', 'Warriors': 'GSW', 'Rockets': 'HOU', 'Pacers': 'IND',
             'Clippers': 'LAC', 'Lakers': 'LAL', 'Grizzlies': 'MEM', 'Heat': 'MIA', 'Bucks': 'MIL', 'Timberwolves': 'MIN',
             'Pelicans': 'NOP', 'Knicks': 'NYK', 'Thunder': 'OKC', 'Magic': 'ORL', '76ers': 'PHI', 'Suns': 'PHX',
             'Trail Blazers': 'POR', 'Kings': 'SAC', 'Spurs': 'SAS', 'Raptors': 'TOR', 'Jazz': 'UTA', 'Wizards': 'WAS'}
BOOK_NAMES = {'draftkings': 'DraftKings', 'fanduel': 'FanDuel', 'betmgm': 'BetMGM', 'williamhill_us': 'Caesars'}
PLAN = {'2025-26': ['2023-24', '2024-25'], '2024-25': ['2023-24']}
MIN_EDGE, STAKE = 0.02, 1.0
SPREAD = {'2025-26': (2.8, 0.4, 5.6, 9.9), '2024-25': (1.5, 0.0, 2.9, 10.0)}
abbr = lambda full: next((a for nick, a in TEAM_ABBR.items() if str(full).endswith(nick)), str(full))


def projections():
    """Noon projections for every line season, each trained only on earlier seasons (as q_policy_test.py)."""
    g = pd.read_parquet(DATA / 'player_games.parquet'); played = g[g['played']].copy()
    rep = pd.read_parquet(DATA / 'noon_injuries.parquet')
    x = load_rows().drop(columns=['out_ppg', 'out_min', 'out_fga', 'n_out']).merge(
        qp.weighted_totals(qp.absence_lists(g, played, rep)['half'], season_averages(played)), on=['GAME_ID', 'TEAM_ID'], how='left')
    x[['out_ppg', 'out_min', 'out_fga', 'n_out']] = x[['out_ppg', 'out_min', 'out_fga', 'n_out']].fillna(0)
    x['out_fga_share'] = x['out_fga'] / x['team_fga_pg']
    x = add_redistribution(x)
    mf, pf, out = selected('minutes'), selected('points'), []
    for s in ['2023-24', '2024-25', '2025-26']:      # 2023-24 projections are the 2024-25 classifier's training rows
        tr = x[x.season < s].copy()
        tr['pred_minutes'] = np.nan
        for t in tr.season.unique():
            tr.loc[tr.season == t, 'pred_minutes'] = fit(tr.loc[tr.season != t, mf], tr.loc[tr.season != t, 'MINUTES']) \
                .predict(tr.loc[tr.season == t, mf])
        mm, pm = fit(tr[mf], tr['MINUTES']), fit(tr[pf], tr['points'])
        a, c = fit_damping(x[x.season < s], mf, pf)
        te = x[x.season == s]
        raw, no_inj = predict_pair(mm, pm, mf, pf, te)
        out.append(te[['PLAYER_ID', 'GAME_ID']].assign(pred=no_inj + damp(raw - no_inj, a, c)))
        print(f'{s}: projections done', flush=True)
    return pd.concat(out), rep


def season_bets(d, test, train):
    tr, te = d[d['season'].isin(train)].reset_index(drop=True), d[d['season'] == test].copy()
    te['p'] = ct.sig(ct.fit_market_fixed(tr, w=ct.season_weights(tr))(te))
    eo = te['p'] - american_to_prob(te['early_best_over_price'])
    eu = (1 - te['p']) - american_to_prob(te['early_best_under_price'])
    te['over_side'], te['edge'] = eo >= eu, np.maximum(eo, eu)
    b = te[~te['status'].isin(['Probable', 'Questionable', 'Doubtful']) & (te['rest_days'] != 1) & (te['edge'] >= MIN_EDGE)]
    b = b.sort_values(['GAME_DATE', 'edge'], ascending=[True, False])
    over = b['over_side'].values
    price = np.where(over, b['early_best_over_price'], b['early_best_under_price']).astype(int)
    win = np.where(over, b['points'] > b['line'], b['points'] < b['line'])
    profit = np.where(price > 0, price / 100, 100 / -price)
    team, home = b['teamName'].map(TEAM_ABBR).fillna(b['teamName']).values, b['home_team'].map(abbr).values
    return pd.DataFrame({
        'date': pd.to_datetime(b['GAME_DATE']).dt.date.astype(str).values, 'player': b['player_name'].values,
        'team': team, 'opponent': np.where(team == home, b['away_team'].map(abbr).values, home),
        'side': np.where(over, 'OVER', 'UNDER'), 'line': b['line'].values, 'price': price,
        'book': [BOOK_NAMES.get(x, x) for x in np.where(over, b['early_best_over_book'], b['early_best_under_book'])],
        'edge': np.round(b['edge'].values, 4), 'stake': STAKE, 'result': np.where(win, 'win', 'loss'),
        'points': b['points'].values, 'units': np.round(np.where(win, profit, -1.0) * STAKE, 2)})


def main():
    proj, rep = projections()
    d = ct.build_dataset(DATA).merge(rep[['GAME_ID', 'PLAYER_ID', 'status']].drop_duplicates(['GAME_ID', 'PLAYER_ID']),
                                     on=['GAME_ID', 'PLAYER_ID'], how='left').merge(proj, on=['PLAYER_ID', 'GAME_ID'])
    d = d.assign(gap=d['pred'] - d['line'], gapz=(d['pred'] - d['line']) / d['pred_sd'])
    seasons = []
    for test, train in PLAN.items():
        bets = season_bets(d, test, train)
        roi, lo, hi, units = SPREAD[test]
        print(f'{test}: {len(bets)} bets, {bets["units"].sum():+.1f}u ({bets["units"].sum() / len(bets):+.1%})')
        when = ' and '.join(train)
        seasons.append({'season': test, 'kind': 'backtest', 'bets': json.loads(bets.to_json(orient='records')),
                        'note': f'Backtest, every eligible prop with a 2%+ edge at 1u: projections trained only on earlier '
                                f'seasons, over/under model trained on {when}. Retrained 10 ways, this season averaged '
                                f'{units:+.1f}u ({roi:+.1f}% per bet, range {lo:+.1f}% to {hi:+.1f}%); shown is one of those runs.'})
    (ROOT / 'site' / 'seasons.json').write_text(json.dumps({'seasons': seasons}, separators=(',', ':')))


if __name__ == '__main__':
    main()
