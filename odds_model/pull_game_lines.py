"""Game spread and total for every game in player_games, from ESPN's free odds feed (resumable).

    python pull_game_lines.py                # every game day not yet saved
    python pull_game_lines.py --date 2026-10-30

Saves data/game_lines.parquet: GAME_ID, home_spread (negative = home favored), total, and the opening numbers
where ESPN has them (2023-24 on; older seasons carry one number, the closing line).
"""
import argparse
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from config import DATA

OUT = DATA / 'game_lines.parquet'
SB = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard'
ODDS = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{e}/competitions/{e}/odds'
S = requests.Session()


def get(url, **kw):
    for _ in range(4):
        try:
            r = S.get(url, timeout=20, **kw)
            if r.status_code == 404:
                return {}
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            continue
    return None


def num(v):
    try:
        return float(str(v).replace('+', ''))
    except (TypeError, ValueError):
        return None


def events(day):
    """[(espn event id, home nickname, away nickname)] for one date."""
    s = get(SB, params={'dates': day.strftime('%Y%m%d')}) or {}
    out = []
    for e in s.get('events', []):
        teams = {c['homeAway']: c['team'].get('shortDisplayName') or c['team']['name']
                 for c in e['competitions'][0]['competitors']}
        out.append((e['id'], teams.get('home'), teams.get('away')))
    return out


def lines(eid):
    s = get(ODDS.format(e=eid)) or {}
    items = [x for x in s.get('items', []) if 'Live' not in x.get('provider', {}).get('name', '')]
    if not items:
        return {}
    x = items[0]
    h = x.get('homeTeamOdds') or {}
    return {'home_spread': num(x.get('spread')), 'total': num(x.get('overUnder')),
            'open_spread': num(((h.get('open') or {}).get('pointSpread') or {}).get('american')),
            'open_total': num(((x.get('open') or {}).get('total') or {}).get('american')
                              if isinstance((x.get('open') or {}).get('total'), dict) else (x.get('open') or {}).get('total')),
            'provider': x.get('provider', {}).get('name')}


def nick(t):
    return {'LA Clippers': 'Clippers', '76ers': '76ers'}.get(t, str(t).split()[-1] if t else t)


def pull(days, games):
    home = games[games['is_home'] == 1].drop_duplicates('GAME_ID')[['GAME_ID', 'GAME_DATE', 'teamName']]
    home = home.assign(day=home['GAME_DATE'].dt.date)
    with ThreadPoolExecutor(8) as ex:
        evs = dict(zip(days, ex.map(events, days)))
    todo = []
    for day, es in evs.items():
        h = home[home['day'] == day]
        for eid, hn, _ in es:
            m = h[h['teamName'].map(nick) == nick(hn)]
            if len(m) == 1:
                todo.append((m['GAME_ID'].iloc[0], eid))
    with ThreadPoolExecutor(8) as ex:
        got = list(ex.map(lambda t: {'GAME_ID': t[0], 'espn_id': t[1], **lines(t[1])}, todo))
    return pd.DataFrame(got)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date')
    args = ap.parse_args()
    games = pd.read_parquet(DATA / 'player_games.parquet', columns=['GAME_ID', 'GAME_DATE', 'teamName', 'is_home'])
    old = pd.read_parquet(OUT) if OUT.exists() else pd.DataFrame(columns=['GAME_ID'])
    if args.date:
        days = [dt.date.fromisoformat(args.date)]
    else:
        have = set(old['GAME_ID'])
        days = sorted({d.date() for d, g in zip(games['GAME_DATE'], games['GAME_ID']) if g not in have})
    print(f'{len(days)} game days to pull', flush=True)
    new = pd.concat([pull(days[i:i + 60], games) for i in range(0, len(days), 60)], ignore_index=True)
    out = pd.concat([old[~old['GAME_ID'].isin(new.get('GAME_ID', []))], new], ignore_index=True)
    out.to_parquet(OUT, index=False)
    n = games['GAME_ID'].nunique()
    print(f'saved {len(out)} games ({out["total"].notna().sum()} with a total) of {n} in player_games')


if __name__ == '__main__':
    main()
