"""College basketball spread data: Odds API snapshots (pull_ncaab_history.py) matched to Torvik's game results.

    python ncaab_data.py        # -> data/ncaab_books.parquet, data/ncaab_games.parquet, data/ncaab_torvik.parquet

ncaab_books   one row per (game, snapshot, book): home/away spread point and price. Snapshot 'morning' is the 10 AM ET
              line (the one bet); 'close' is the last snapshot 5+ minutes before tip.
ncaab_games   one row per game with a 10 AM line and a Torvik result: date, teams (Torvik names), location from the
              Odds API home team's side (H/A/N), final score, consensus spread at 10 AM and at the close.
ncaab_torvik  every Division I game from Torvik (one row per game): date, teams, location, points, possessions.

Team names: the Odds API says "Arkansas-Little Rock Trojans", Torvik "Little Rock". Each team is matched per season by
its schedule (the set of dates it played, nearly unique over a season) with name similarity as a tie-break, then every
game is checked: both teams must meet on that date in Torvik.
"""
import csv
import datetime as dt
import difflib
import glob
import gzip
import json
import re
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from unidecode import unidecode

from config import DATA

ET = ZoneInfo('America/New_York')
RAW = DATA / 'ncaab_raw'
TORVIK = DATA / 'ncaab_torvik'
BET_BOOKS = ['draftkings', 'fanduel', 'betmgm', 'williamhill_us']     # the four books the site uses
YEAR = {'2020-21': 2021, '2021-22': 2022, '2022-23': 2023, '2023-24': 2024, '2024-25': 2025, '2025-26': 2026, '2026-27': 2027}


def season_of_year(y):
    return f'{y - 1}-{str(y)[2:]}'


# ---------------------------------------------------------------- Torvik

def load_torvik():
    """One row per game (Torvik lists each game twice, once per team): date, team, opp, loc of `team`, points, poss."""
    rows = []
    for path in sorted(glob.glob(str(TORVIK / 'gamestats_*.csv'))):
        year = int(re.search(r'(\d{4})', path).group(1))
        for r in csv.reader(open(path)):
            if len(r) < 24 or r[6][:1] not in 'WL':
                continue
            won = r[6][0] == 'W'
            hi, lo = (int(x) for x in re.findall(r'\d+', r[6])[:2])
            rows.append({'season': season_of_year(year), 'date': pd.Timestamp(dt.datetime.strptime(r[0], '%m/%d/%y')),
                         'gtype': int(r[1]), 'team': r[2], 'opp': r[4], 'loc': r[5],
                         'pts': hi if won else lo, 'opp_pts': lo if won else hi, 'poss': float(r[23])})
    t = pd.DataFrame(rows)
    # keep one row per game: the home team's, or the alphabetically first team's at a neutral site
    keep = (t['loc'] == 'H') | ((t['loc'] == 'N') & (t['team'] < t['opp']))
    return t[keep].drop_duplicates(['date', 'team', 'opp']).reset_index(drop=True)


# ---------------------------------------------------------------- Odds API

def load_books():
    """Every (game, snapshot, book) spread from the raw snapshots."""
    rows = []
    for path in sorted(glob.glob(str(RAW / '*' / '*.json.gz'))):
        season = path.split('/')[-2]
        d = json.loads(gzip.decompress(open(path, 'rb').read()))
        ts = pd.Timestamp(d['timestamp'])
        morning = path.endswith('_1000.json.gz')
        for e in d.get('data') or []:
            tip = pd.Timestamp(e['commence_time'])
            for b in e.get('bookmakers') or []:
                m = next((m for m in b.get('markets', []) if m['key'] == 'spreads'), None)
                if not m:
                    continue
                o = {x['name']: x for x in m['outcomes']}
                h, a = o.get(e['home_team']), o.get(e['away_team'])
                if not h or not a or h.get('point') is None or a.get('point') is None:
                    continue
                rows.append({'season': season, 'event_id': e['id'], 'ts': ts, 'morning': morning, 'tip': tip,
                             'home': e['home_team'], 'away': e['away_team'], 'book': b['key'],
                             'home_point': float(h['point']), 'home_price': int(h['price']),
                             'away_point': float(a['point']), 'away_price': int(a['price'])})
    b = pd.DataFrame(rows)
    b = b[(b['tip'] - b['ts']) >= pd.Timedelta(minutes=5)]                      # pre-game lines only
    b['date'] = b['tip'].dt.tz_convert(ET).dt.tz_localize(None).dt.normalize()
    mor = b[b['morning']].assign(snap='morning')
    close = b[b['ts'] == b.groupby('event_id')['ts'].transform('max')].assign(snap='close')   # latest pre-tip snapshot
    return pd.concat([mor, close], ignore_index=True).drop(columns='morning')


# ---------------------------------------------------------------- names

def norm(s):
    s = unidecode(s).lower().replace('&', ' and ').replace('-', ' ')
    s = re.sub(r"[.'()]", '', s)
    s = re.sub(r'\bstate\b', 'st', s)
    return re.sub(r'\s+', ' ', s).strip()


def name_sim(odds, tv):
    o, t = norm(odds), norm(tv)
    if o.startswith(t + ' '):
        return 1.0
    return difflib.SequenceMatcher(None, o, t).ratio()


def match_names(games_odds, tv, season):
    """{odds name: torvik name} for one season, by schedule overlap (+ name similarity as a tie-break)."""
    g = games_odds[games_odds['season'] == season]
    t = tv[tv['season'] == season]
    od = {}
    for side in ('home', 'away'):
        for n, d in g.groupby(side)['date']:
            od.setdefault(n, set()).update(d)
    td = {}
    for side in ('team', 'opp'):
        for n, d in t.groupby(side)['date']:
            td.setdefault(n, set()).update(d)
    # a game late at night ET can be listed on the next day: count a date as shared if within a day
    td_wide = {n: s | {x + pd.Timedelta(days=1) for x in s} | {x - pd.Timedelta(days=1) for x in s} for n, s in td.items()}
    on, tn = sorted(od), sorted(td)
    score = np.zeros((len(on), len(tn)))
    for i, o in enumerate(on):
        for j, tt in enumerate(tn):
            shared = len(od[o] & td_wide[tt])
            score[i, j] = shared / max(1, len(od[o] | td[tt])) + 0.3 * name_sim(o, tt)
    r, c = linear_sum_assignment(-score)
    return {on[i]: tn[j] for i, j in zip(r, c) if score[i, j] > 0.5}


# ---------------------------------------------------------------- games

def consensus(b):
    """Per game: median home spread across books, number of books."""
    return b.groupby('event_id').agg(spread=('home_point', 'median'), n_books=('book', 'nunique'))


def build():
    tv = load_torvik()
    books = load_books()
    ev = books[books['snap'] == 'morning'].drop_duplicates('event_id')[['season', 'event_id', 'date', 'tip', 'home', 'away']]
    out = []
    for season in sorted(ev['season'].unique()):
        names = match_names(ev, tv, season)
        e = ev[ev['season'] == season].assign(t_home=lambda x: x['home'].map(names), t_away=lambda x: x['away'].map(names))
        t = tv[tv['season'] == season]
        # each odds game -> the Torvik game between those two teams within a day of it
        cand = pd.concat([t.rename(columns={'team': 't_home', 'opp': 't_away'}).assign(flip=False),
                          t.rename(columns={'team': 't_away', 'opp': 't_home', 'pts': 'opp_pts', 'opp_pts': 'pts'}).assign(flip=True)])
        m = e.merge(cand, on=['t_home', 't_away'], suffixes=('', '_tv'))
        m = m[(m['date'] - m['date_tv']).abs() <= pd.Timedelta(days=1)]
        m = m.sort_values(['event_id']).drop_duplicates('event_id')
        # location from the Odds API home team's side; Torvik rows are the home team's (or a neutral pick)
        m['loc'] = np.where(m['loc'] == 'N', 'N', np.where(m['flip'], 'A', 'H'))
        m = m.rename(columns={'pts': 'home_pts', 'opp_pts': 'away_pts'})
        print(f'{season}: {len(names)} of {e["home"].nunique() + 0} names matched; '
              f'{len(m)} of {len(e)} games found in Torvik ({len(m) / len(e):.1%})')
        out.append(m[['season', 'event_id', 'date', 'tip', 'home', 'away', 't_home', 't_away', 'loc', 'gtype',
                      'home_pts', 'away_pts', 'poss']])
    games = pd.concat(out, ignore_index=True)
    mor, clo = (consensus(books[books['snap'] == s]) for s in ('morning', 'close'))
    games = games.join(mor, on='event_id').join(clo.rename(columns={'spread': 'close_spread', 'n_books': 'close_books'}), on='event_id')
    last = books[books['snap'] == 'close'].groupby('event_id').agg(close_ts=('ts', 'max'))
    games = games.join(last, on='event_id')
    games['close_lead_min'] = (games['tip'] - games['close_ts']).dt.total_seconds() / 60
    books.to_parquet(DATA / 'ncaab_books.parquet')
    games.to_parquet(DATA / 'ncaab_games.parquet')
    tv.to_parquet(DATA / 'ncaab_torvik.parquet')
    return games


if __name__ == '__main__':
    g = build()
    print(g.groupby('season').agg(games=('event_id', 'size'), neutral=('loc', lambda x: (x == 'N').mean()),
                                  books=('n_books', 'median'), close_lead=('close_lead_min', 'median')).round(2))
