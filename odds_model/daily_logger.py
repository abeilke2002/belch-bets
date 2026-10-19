"""Log live player-points lines going forward (same file format as the historical pull).

    python daily_logger.py early              # ~noon ET: snapshot every game tipping today
    python daily_logger.py close --window 45  # run every 15 min: snapshot games starting soon
    python daily_logger.py results            # next morning: pull finished box scores

Costs: listing events is free; each game snapshot is 1 credit (1 market x 1 region).
Parse with:  python parse_odds.py --raw-dir data/odds_live
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
from zoneinfo import ZoneInfo

from config import LIVE, MARKET, REGIONS, ROOT, SPORT
from odds_api import CreditLimit, OddsAPI

ET = ZoneInfo('America/New_York')


def season_label(day):
    y = day.year if day.month >= 8 else day.year - 1
    return f'{y}-{(y + 1) % 100:02d}'


def snapshot(api, events, snap):
    saved = 0
    for e in events:
        out = LIVE / f"{e['id']}_{snap}.json"
        if out.exists():
            continue
        data = api.get(f"/sports/{SPORT}/events/{e['id']}/odds", expected_cost=len(REGIONS.split(',')),
                       regions=REGIONS, markets=MARKET, oddsFormat='american', includeLinks='true')
        now = dt.datetime.now(dt.timezone.utc)
        day = dt.datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00')).astimezone(ET).date()
        out.write_text(json.dumps({'timestamp': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'data': data,
                                   '_meta': {'event': e, 'snapshot': snap, 'season': season_label(day)}}))
        saved += 1
    return saved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['early', 'close', 'results'])
    ap.add_argument('--window', type=int, default=45, help='close: minutes before tip to snapshot')
    args = ap.parse_args()

    if args.mode == 'results':
        season = season_label(dt.datetime.now(ET).date() - dt.timedelta(days=1))
        subprocess.run([sys.executable, str(ROOT / 'pull_box_scores.py'), '--season', season], check=True)
        return

    api = OddsAPI()
    now = dt.datetime.now(dt.timezone.utc)
    events = api.get(f'/sports/{SPORT}/events', expected_cost=0) or []
    start = lambda e: dt.datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00'))
    if args.mode == 'early':
        today = now.astimezone(ET).date()
        events = [e for e in events if start(e).astimezone(ET).date() == today and start(e) > now]
    else:
        events = [e for e in events if now < start(e) <= now + dt.timedelta(minutes=args.window)]

    try:
        saved = snapshot(api, events, args.mode)
    except CreditLimit as ex:
        print(f'Stopped: {ex}')
        saved = 0
    print(f'{args.mode}: {len(events)} games in window, {saved} new snapshots | '
          f'credits remaining {api.remaining}')


if __name__ == '__main__':
    main()
