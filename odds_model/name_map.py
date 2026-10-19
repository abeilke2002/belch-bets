"""Match Odds API events/players to NBA GAME_ID/PLAYER_ID -> data/name_map.parquet.

Unmatched names are added to data/name_overrides.csv; fill in PLAYER_ID there and rerun.
"""
import argparse
import difflib
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from unidecode import unidecode

from config import DATA

SUFFIX = re.compile(r'\b(jr|sr|ii|iii|iv)\b')


def norm(name):
    s = re.sub(r'\([^)]*\)', ' ', str(name))                     # drop team tags like "(Det)"
    s = unidecode(s).lower().replace('.', ' ').replace("'", '').replace('-', ' ')
    return re.sub(r'\s+', ' ', SUFFIX.sub('', s)).strip()


def roster_match(key, cand):
    """Match within one game's roster when the book abbreviates or reorders a name: same tokens in another
    order, or same last name with a first name that is an initial/prefix of the NBA one (or vice versa:
    "P." -> Payton, "Herb" -> Herbert, "Cameron" -> Cam). Different first names never match (Stephen is
    not Seth). Returns a PLAYER_ID only when exactly one player fits."""
    toks = key.split()
    if len(toks) < 2:
        return None
    cand = cand.assign(toks=cand['key'].str.split())
    same_set = cand[cand['toks'].apply(lambda t: sorted(t) == sorted(toks))]
    if len(same_set) == 1:
        return same_set['PLAYER_ID'].iloc[0]
    first, last = toks[0], toks[-1]

    def fits(t):
        if len(t) < 2 or t[-1] != last:
            return False
        return t[0].startswith(first) or first.startswith(t[0])
    hit = cand[cand['toks'].apply(fits)]
    return hit['PLAYER_ID'].iloc[0] if len(hit) == 1 else None


def match_games(lines, games):
    """Event -> GAME_ID by ET game date + both team nicknames (handles LA vs Los Angeles)."""
    ev = lines.drop_duplicates('event_id')[['event_id', 'commence_time', 'home_team', 'away_team']].copy()
    ev['date'] = (pd.to_datetime(ev['commence_time'], utc=True)
                  .dt.tz_convert(ZoneInfo('America/New_York')).dt.normalize().dt.tz_localize(None))
    teams = games.groupby(['GAME_ID', 'GAME_DATE'])['teamName'].apply(set).reset_index()

    out = {}
    for r in ev.itertuples():
        for shift in (0, -1, 1):                    # tolerate a date off by one
            day = teams[teams['GAME_DATE'] == r.date + pd.Timedelta(days=shift)]
            hit = day[day['teamName'].apply(
                lambda ts: all(any(full.endswith(t) for t in ts) for full in (r.home_team, r.away_team)))]
            if len(hit) == 1:
                out[r.event_id] = hit['GAME_ID'].iloc[0]
                break
    return pd.Series(out, name='GAME_ID')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', default=DATA)
    args = ap.parse_args()
    d = Path(args.data_dir)
    OVERRIDES = d / 'name_overrides.csv'

    lines = pd.read_parquet(d / 'odds_lines.parquet')
    games = pd.read_parquet(DATA / 'player_games.parquet',
                            columns=['GAME_ID', 'GAME_DATE', 'PLAYER_ID', 'teamName', 'player_name'])
    games['key'] = games['player_name'].map(norm)

    game_ids = match_games(lines, games)
    lines = lines.merge(game_ids, left_on='event_id', right_index=True, how='left')
    print(f'games matched: {lines.drop_duplicates("event_id").GAME_ID.notna().mean():.1%}')

    overrides = pd.read_csv(OVERRIDES) if OVERRIDES.exists() else \
        pd.DataFrame(columns=['odds_name', 'PLAYER_ID'])
    ov = overrides.dropna(subset=['PLAYER_ID']).set_index('odds_name')['PLAYER_ID'].astype(int)
    roster = {g: v for g, v in games.groupby('GAME_ID')}
    # Players not in a game's box score at all (inactive) are still known league-wide: those bets void
    known = games.drop_duplicates('key').set_index('key')['PLAYER_ID']

    # Fast path: exact name match within the game, as one merge (about 94% of rows)
    lines['key'] = lines['player'].map(norm)
    exact = games.drop_duplicates(['GAME_ID', 'key']).groupby(['GAME_ID', 'key'])['PLAYER_ID'].first()
    pid = pd.Series(lines.set_index(['GAME_ID', 'key']).index.map(exact.to_dict()), index=lines.index)
    how = pd.Series(np.where(pid.notna(), 'exact', ''), index=lines.index, dtype=object)
    ov_hit = lines['player'].isin(ov.index)
    pid[ov_hit], how[ov_hit] = lines.loc[ov_hit, 'player'].map(ov), 'override'

    for i in lines.index[how == '']:
        r = lines.loc[i]
        cand = roster.get(r['GAME_ID'])
        if cand is None:
            how[i] = 'no game'; continue
        # A real player who isn't in this game's box score didn't play: void the bet. Checked before any
        # looser match so LeBron James can never be matched to Bronny James.
        if r['key'] in known.index:
            pid[i], how[i] = known[r['key']], 'inactive (void)'; continue
        rm = roster_match(r['key'], cand)
        if rm is not None:
            pid[i], how[i] = rm, 'roster'; continue
        # No fuzzy guess when the book gives only an initial ("J. Green" could be Josh, Jalen or Jeff)
        initial_only = len(r['key'].split()[0]) <= 2
        close = [] if initial_only else difflib.get_close_matches(r['key'], cand['key'].tolist(), n=1, cutoff=0.85)
        if close:
            pid[i], how[i] = cand.loc[cand['key'] == close[0], 'PLAYER_ID'].iloc[0], 'fuzzy'
        else:
            how[i] = 'unmatched'
    lines['PLAYER_ID'], lines['match'] = pid.astype('float'), how

    print(lines['match'].value_counts(normalize=True).round(4).to_string())
    unmatched = sorted(set(lines.loc[lines['match'] == 'unmatched', 'player']) - set(overrides['odds_name']))
    if unmatched:
        new = pd.concat([overrides, pd.DataFrame({'odds_name': unmatched, 'PLAYER_ID': None})])
        new.to_csv(OVERRIDES, index=False)
        print(f'{len(unmatched)} new unmatched names added to {OVERRIDES.name} '
              f'(e.g. {unmatched[:5]}); fill in PLAYER_ID and rerun')
    fuzzy = lines[lines['match'] == 'fuzzy'].drop_duplicates('player')
    if len(fuzzy):
        print(f'fuzzy matches to spot-check: {fuzzy.player.tolist()[:10]}')

    lines[['event_id', 'player', 'GAME_ID', 'PLAYER_ID', 'match']].to_parquet(
        d / 'name_map.parquet', index=False)


if __name__ == '__main__':
    main()
