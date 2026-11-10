"""Historical men's college basketball spreads from The Odds API, for testing a spread model.

    python pull_ncaab_history.py --plan 2025-02-15          # what one day would pull (costs only that day's morning call)
    python pull_ncaab_history.py --seasons 2026-27 2025-26 2024-25 --floor 4000

Per game day (ET):
  morning  10:00 AM ET: every game tipping that day (the line we would bet). One call covers the whole slate.
  close    more snapshots, placed from the morning's tip times so every game has one 5-180 minutes before its tip
           (the closing line, for closing-line value). Fewest snapshots that cover all tips (greedy, earliest tip first);
           one that would serve fewer than 3 games is skipped and those games keep their latest earlier line.
Each call is 10 credits (spreads, US books); a call with no games is free. Raw responses are kept gzipped in
data/ncaab_raw/{season}/{date}_{HHMM}.json.gz (local only, like data/odds_raw) and never pulled twice, so the run
resumes where it stopped. Historical odds need a paid plan: pull while the subscription is active.
"""
import argparse
import datetime as dt
import gzip
import json
from zoneinfo import ZoneInfo

from config import DATA
from odds_api import CreditLimit, OddsAPI

ET, UTC = ZoneInfo('America/New_York'), dt.timezone.utc
OUT = DATA / 'ncaab_raw'
SPORT = 'basketball_ncaab'
MORNING = dt.time(10, 0)
LEAD_MIN, LEAD_MAX = 5, 180          # a closing snapshot must be this many minutes before tip
MIN_GAMES = 3                        # ...and serve at least this many games, or those games keep an earlier line
SEASONS = {                          # regular season through the national title game, with a little room on each end
    '2026-27': ('2026-11-01', None),     # through yesterday
    '2025-26': ('2025-11-01', '2026-04-08'),
    '2024-25': ('2024-11-01', '2025-04-09'),
    '2023-24': ('2023-11-01', '2024-04-10'),
    '2022-23': ('2022-11-01', '2023-04-05'),
    '2021-22': ('2021-11-01', '2022-04-06'),
}


def iso(t):
    return t.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def day_window(day):
    """Tips on the ET date `day`: from midnight ET to 6 AM ET the next day (late Hawaii tips)."""
    start = dt.datetime.combine(day, dt.time(0), ET)
    return start, start + dt.timedelta(hours=30)


def path_for(season, day, t):
    return OUT / season / f"{day}_{t.astimezone(ET):%H%M}.json.gz"


def fetch(api, season, day, t):
    """The snapshot at time t (games tipping later that ET day), from disk if pulled before. None = no games."""
    p = path_for(season, day, t)
    if p.exists():
        return json.loads(gzip.decompress(p.read_bytes()))
    _, end = day_window(day)
    r = api.get(f'/historical/sports/{SPORT}/odds', expected_cost=10, regions='us', markets='spreads',
                oddsFormat='american', date=iso(t), commenceTimeFrom=iso(t), commenceTimeTo=iso(end))
    if r is None:
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(gzip.compress(json.dumps({'requested': iso(t), **r}).encode()))
    return r


def tips(snap):
    """Tip time of every game with a line (repeats kept: a 7 PM slot with 30 games counts 30)."""
    return sorted(dt.datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00'))
                  for e in (snap or {}).get('data') or [] if e.get('bookmakers'))


def close_times(morning_t, tip_times):
    """Fewest snapshot times so every tip has one LEAD_MIN-LEAD_MAX minutes before it (the morning snapshot counts).
    A snapshot that would serve fewer than MIN_GAMES games is skipped: those few keep their latest earlier line."""
    ok = lambda tip, s: dt.timedelta(minutes=LEAD_MIN) <= tip - s <= dt.timedelta(minutes=LEAD_MAX)
    out, covered_by = [], [morning_t]
    for tip in tip_times:
        if any(ok(tip, s) for s in covered_by):
            continue
        s = tip - dt.timedelta(minutes=LEAD_MIN + 5)
        covered_by.append(s)
        if sum(ok(t, s) and not any(ok(t, c) for c in covered_by[:-1]) for t in tip_times) >= MIN_GAMES:
            out.append(s)
    return out


def pull_day(api, season, day):
    m = dt.datetime.combine(day, MORNING, ET)
    snap = fetch(api, season, day, m)
    tt = tips(snap)
    if not tt:
        return 0, 0
    closes = close_times(m, tt)
    for s in closes:
        fetch(api, season, day, s)
    return len(tt), 1 + len(closes)


def days(season):
    a, b = SEASONS[season]
    d0 = dt.date.fromisoformat(a)
    d1 = dt.date.fromisoformat(b) if b else dt.datetime.now(ET).date() - dt.timedelta(days=1)
    return [d0 + dt.timedelta(days=i) for i in range((d1 - d0).days + 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', nargs='+', default=list(SEASONS))
    ap.add_argument('--plan', help='one ET date: pull its morning snapshot and print the closing-snapshot plan')
    ap.add_argument('--floor', type=int, default=4000, help='stop when remaining credits would fall below this')
    ap.add_argument('--max-credits', type=int, help='stop after spending this many credits in this run')
    args = ap.parse_args()
    api = OddsAPI(floor=args.floor, max_credits=args.max_credits)
    if args.plan:
        day = dt.date.fromisoformat(args.plan)
        season = next(s for s in SEASONS if days(s)[0] <= day <= (days(s)[-1] if SEASONS[s][1] else day))
        m = dt.datetime.combine(day, MORNING, ET)
        tt = tips(fetch(api, season, day, m))
        cl = close_times(m, tt)
        print(f'{day}: {len(tt)} games, {1 + len(cl)} snapshots: morning + ' +
              ', '.join(f'{s.astimezone(ET):%-I:%M %p}' for s in cl) + f' | credits left {api.remaining}')
        return
    try:
        for season in args.seasons:
            games = snaps = 0
            for day in days(season):
                g, s = pull_day(api, season, day)
                games, snaps = games + g, snaps + s
            print(f'{season}: {snaps} snapshots on game days, credits spent so far {api.spent}, left {api.remaining}', flush=True)
    except CreditLimit as e:
        print(f'stopped: {e}')
    print(f'done: spent {api.spent} credits this run, {api.remaining} left')


if __name__ == '__main__':
    main()
