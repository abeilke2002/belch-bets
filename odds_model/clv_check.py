"""Line movement on today's bets (workflow mode 'clv'): the market at noon vs now, pulling only the games and markets
with bets that haven't tipped (1 credit per market per game, about 5 a night). Prints the comparison; saves nothing.
Fair read: the no-vig chance of our side averaged over every book offering our exact line, noon vs now, and where each
book's line sits now (a better number for us, or worse)."""
import datetime as dt
import json
import sys

import requests
from config import API_KEY, DATA

MK = {'points': 'player_points', 'rebounds': 'player_rebounds', 'assists': 'player_assists'}
prob = lambda a: 100 / (a + 100) if a > 0 else -a / (-a + 100)
s = json.load(open(DATA / 'site' / 'picks.json'))
started = lambda p: dt.datetime.fromisoformat(p['commence_time'].replace('Z', '+00:00')) <= dt.datetime.now(dt.timezone.utc)
for p in s['picks']:
    if started(p):
        print(f"{p['player']} {p['market']}: game has tipped, props are off the board (skipped)")
picks = [p for p in s['picks'] if not started(p)]
need = {}
for p in picks:
    need.setdefault(p['event_id'], set()).add(MK[p['market']])
now = {}
for e, ms in need.items():
    r = requests.get(f'https://api.the-odds-api.com/v4/sports/basketball_nba/events/{e}/odds',
                     params=dict(apiKey=API_KEY, regions='us', markets=','.join(sorted(ms)), oddsFormat='american'), timeout=30)
    print(f'{e[:8]} {sorted(ms)}: HTTP {r.status_code}, cost {r.headers.get("x-requests-last")}, left {r.headers.get("x-requests-remaining")}')
    if r.status_code != 200:
        print(r.text[:200]); sys.exit(1)
    now[e] = {'data': r.json()}


def books(d, name, mkey):
    out = {}
    for b in d['data'].get('bookmakers', []):
        for m in b['markets']:
            if m['key'] != mkey:
                continue
            o = {x['name']: x for x in m['outcomes'] if x.get('description') == name}
            if 'Over' in o and 'Under' in o:
                out[b['key']] = (o['Under']['point'], o['Over']['price'], o['Under']['price'])
    return out


BK = {'DraftKings': 'draftkings', 'FanDuel': 'fanduel', 'BetMGM': 'betmgm', 'Caesars': 'williamhill_us'}
print()
for p in picks:
    mk = MK[p['market']]
    a = books(json.load(open(DATA / 'odds_live' / f"{p['event_id']}_early.json")), p['player'], mk)    # the noon snapshot
    b = books(now[p['event_id']], p['player'], mk)
    side = (lambda ov, un: prob(un) / (prob(ov) + prob(un))) if p['side'] == 'UNDER' else (lambda ov, un: prob(ov) / (prob(ov) + prob(un)))
    avg = lambda d: (lambda c: (sum(side(*d[k][1:]) for k in c) / len(c), len(c)) if c else (None, 0))([k for k in d if d[k][0] == p['line']])
    (na, nn), (la, ln) = avg(a), avg(b)
    lines = sorted({v[0] for v in b.values()})
    toward = sum((v[0] < p['line']) if p['side'] == 'UNDER' else (v[0] > p['line']) for v in b.values())
    away = sum((v[0] > p['line']) if p['side'] == 'UNDER' else (v[0] < p['line']) for v in b.values())
    mine = b.get(BK.get(p['book']))
    f = lambda x: f'{x * 100:.1f}%' if x is not None else '--'
    print(f"{p['player']:20} {p['market'][:3]} {p['side'][0]}{p['line']} {p['price']:+d} {p['book'][:3]} | our side at {p['line']}: noon {f(na)} ({nn} books) -> now {f(la)} ({ln} books)"
          f"{f' = {(la - na) * 100:+.1f} pts' if na is not None and la is not None else ''} | books now at a better line for us: {toward}, worse: {away}"
          f" | lines now {lines} | {p['book']} now {mine}")
