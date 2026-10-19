"""Pull the NBA's official injury reports as of noon ET on each game day (free, via nbainjuries).

For each game date: the 12:00 PM ET report (matches the noon odds snapshot). If any team is marked
"NOT YET SUBMITTED" at noon, the latest report from the previous evening (10, 8 or 5 PM ET) is also
saved; teams missing from both are handled later with their previous-game absences. Parsed reports are cached as CSV in data/injury_reports/ (resumable).

nbainjuries reads the PDFs with tabula (Java). Your anaconda Python is an Intel build, so it needs an
Intel Java: config.JAVA_X64_HOME (Temurin 17 x64 in ~/Library/Java-x64).

    python pull_injury_reports.py                 # all seasons in config.SEASONS
    python pull_injury_reports.py --date 2025-01-15
"""
import argparse
import datetime as dt
import os
import time

import pandas as pd

from config import DATA, JAVA_X64_HOME, SEASONS

if JAVA_X64_HOME:                                        # must be set before nbainjuries starts the JVM
    os.environ['JAVA_HOME'] = JAVA_X64_HOME             # (on Linux / GitHub Actions the system Java is used)
from nbainjuries import injury  # noqa: E402

OUT_DIR = DATA / 'injury_reports'
OUT_DIR.mkdir(exist_ok=True)


def fetch(ts, path):
    """Parsed report at timestamp ts (ET, naive), cached at path. Returns a DataFrame or None."""
    if path.exists():
        return pd.read_csv(path)
    try:
        df = injury.get_reportdata(ts, return_df=True)
    except Exception as e:
        print(f'  {ts:%Y-%m-%d %H:%M}: not available ({type(e).__name__})', flush=True)
        return None
    df.to_csv(path, index=False)
    return df


def game_dates(season):
    games = pd.read_parquet(DATA / 'player_games.parquet', columns=['GAME_DATE', 'season'])
    start, end = SEASONS[season]
    d = games.loc[games['season'] == season, 'GAME_DATE'].drop_duplicates()
    return sorted(x.date() for x in d if start <= str(x.date()) <= end)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', nargs='+', default=list(SEASONS))
    ap.add_argument('--date')
    args = ap.parse_args()
    dates = [dt.date.fromisoformat(args.date)] if args.date else \
        [d for s in args.seasons for d in game_dates(s)]

    missing, fallbacks = [], 0
    for i, d in enumerate(dates, 1):
        noon = fetch(dt.datetime(d.year, d.month, d.day, 12, 0), OUT_DIR / f'{d}_noon.csv')
        if noon is None:
            missing.append(d)
        elif noon['Reason'].astype(str).str.contains('NOT YET SUBMITTED').any():
            prev = d - dt.timedelta(days=1)
            path = OUT_DIR / f'{d}_prevday.csv'
            for hour in (22, 20, 17):              # latest report from the previous evening
                if fetch(dt.datetime(prev.year, prev.month, prev.day, hour, 0), path) is not None:
                    break
            fallbacks += 1
        if i % 25 == 0:
            print(f'{i}/{len(dates)} game days', flush=True)
        time.sleep(0.3)
    print(f'done: {len(dates)} game days | noon reports missing: {len(missing)} {missing[:5]} | '
          f'days needing the previous-day fallback: {fallbacks}')


if __name__ == '__main__':
    main()
