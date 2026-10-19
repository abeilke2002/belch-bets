"""Pull historical NBA player-points lines (early + close snapshot per game) from The Odds API.

Resumable: every response is saved under data/odds_raw/ and existing files are skipped.

    python pull_historical_odds.py --test 3            # try 3 games, print cost per game
    python pull_historical_odds.py --max-credits 85000 # full pull
"""
import argparse
import datetime as dt
import json
from zoneinfo import ZoneInfo

import pandas as pd

from config import (CLOSE_LEAD_MINUTES, COST_EVENT_ODDS, COST_EVENTS, EARLY_ET_HOUR, EARLY_MIN_LEAD_HOURS,
                    EVENTS_UTC_HOUR, MARKET, RAW, RAW_EVENTS, REGIONS, SEASONS, SPORT)
from odds_api import CreditLimit, OddsAPI

ET = ZoneInfo('America/New_York')


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_time(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))


def snapshot_time(commence, snap, close_lead=CLOSE_LEAD_MINUTES):
    if snap.startswith('close'):
        return commence - dt.timedelta(minutes=close_lead)
    game_day = commence.astimezone(ET).date()
    early = dt.datetime(game_day.year, game_day.month, game_day.day, EARLY_ET_HOUR, tzinfo=ET)
    return min(early, commence - dt.timedelta(hours=EARLY_MIN_LEAD_HOURS))


def events_for_date(api, date):
    """Events tipping off on this ET date; the list is cached so reruns cost nothing."""
    cache = RAW_EVENTS / f'{date}.json'
    if cache.exists():
        resp = json.loads(cache.read_text())
    else:
        resp = api.get(f'/historical/sports/{SPORT}/events', expected_cost=COST_EVENTS,
                       date=f'{date}T{EVENTS_UTC_HOUR:02d}:00:00Z') or {'data': []}
        cache.write_text(json.dumps(resp))
    return [e for e in resp.get('data', [])
            if parse_time(e['commence_time']).astimezone(ET).date().isoformat() == date]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', nargs='+', default=list(SEASONS))
    ap.add_argument('--snapshots', nargs='+', default=['early', 'close'], choices=['early', 'close'])
    ap.add_argument('--test', type=int, help='stop after this many games')
    ap.add_argument('--date', help='pull only this game date (YYYY-MM-DD), e.g. to check one slate')
    ap.add_argument('--max-credits', type=int, help='stop before spending more than this')
    ap.add_argument('--probe-close', nargs='*', type=int, metavar='MIN',
                    help='with --test: also pull close snapshots this many minutes before tip, to compare')
    args = ap.parse_args()
    if args.date:
        season = next((s for s, (a, b) in SEASONS.items() if a <= args.date <= b), None)
        if season is None:
            raise SystemExit(f'{args.date} is outside the configured regular seasons {SEASONS}')
        plan = [(season, [args.date])]
    else:
        plan = [(s, pd.date_range(*SEASONS[s]).strftime('%Y-%m-%d')) for s in args.seasons]
    probing = args.test or args.date

    api = OddsAPI(max_credits=args.max_credits)
    games = calls = empty = 0
    pulled_ids = []
    try:
        for season, dates in plan:
            for date in dates:
                events = events_for_date(api, date)
                for e in events:
                    commence = parse_time(e['commence_time'])
                    pulled = False
                    for snap in args.snapshots:
                        out = RAW / f"{e['id']}_{snap}.json"
                        if out.exists():
                            continue
                        resp = api.get(f"/historical/sports/{SPORT}/events/{e['id']}/odds",
                                       expected_cost=COST_EVENT_ODDS * len(REGIONS.split(',')),
                                       regions=REGIONS, markets=MARKET, oddsFormat='american',
                                       date=iso(snapshot_time(commence, snap)))
                        resp = resp or {'data': None}
                        resp['_meta'] = {'event': e, 'snapshot': snap, 'season': season}
                        out.write_text(json.dumps(resp))
                        calls += 1
                        pulled = True
                        if not (resp.get('data') or {}).get('bookmakers'):
                            empty += 1
                    games += pulled
                    pulled_ids.append(e['id'])
                    for lead in (args.probe_close or []) if probing else []:
                        probe = RAW / 'probe' / f"{e['id']}_close{lead}.json"
                        if probe.exists():
                            continue
                        probe.parent.mkdir(exist_ok=True)
                        resp = api.get(f"/historical/sports/{SPORT}/events/{e['id']}/odds",
                                       expected_cost=COST_EVENT_ODDS, regions=REGIONS, markets=MARKET,
                                       oddsFormat='american', date=iso(snapshot_time(commence, 'close', lead)))
                        probe.write_text(json.dumps(resp or {'data': None}))
                    if args.test and games >= args.test:
                        raise StopIteration
                print(f'{date}: {len(events)} games | spent {api.spent} | remaining {api.remaining}',
                      flush=True)
    except StopIteration:
        pass
    except CreditLimit as ex:
        print(f'Stopped: {ex}')

    print(f'\nGames pulled: {games} | snapshot calls: {calls} (empty: {empty}) | '
          f'credits spent: {api.spent} | remaining: {api.remaining}')
    if games:
        print(f'Average cost per game: {api.spent / games:.1f} credits')
    if probing:
        report_test(pulled_ids)


def report_test(event_ids):
    """Lines per snapshot for the pulled games: are early and close both populated, and how late is safe?"""
    rows = []
    files = list(RAW.glob('*.json')) + list((RAW / 'probe').glob('*.json'))
    for f in sorted(f for f in files if f.name.split('_')[0] in event_ids):
        resp = json.loads(f.read_text())
        data = resp.get('data') or {}
        books = data.get('bookmakers', [])
        players = {o.get('description') for b in books for m in b.get('markets', []) for o in m['outcomes']}
        snap = f.stem.split('_', 1)[1]
        rows.append({'game': f"{data.get('away_team', '?')} @ {data.get('home_team', '?')}", 'snapshot': snap,
                     'time (UTC)': resp.get('timestamp'), 'books': len(books), 'players with lines': len(players)})
    t = pd.DataFrame(rows)
    print(t.to_string(index=False))
    if len(t):
        print('\nAverage players with lines by snapshot:')
        print(t.groupby('snapshot')[['books', 'players with lines']].mean().round(1).to_string())


if __name__ == '__main__':
    main()
