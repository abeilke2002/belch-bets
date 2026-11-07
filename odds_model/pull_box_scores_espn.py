"""Box scores from ESPN, written in the same format as pull_box_scores.py.

stats.nba.com and cdn.nba.com refuse requests from cloud servers (GitHub Actions), so the daily cloud run
gets box scores from ESPN's public game data instead. Output matches what build_features.load_box reads:

    csvs/{tag}_all_box.csv      one row per player per game (tag 2027 = 2026-27 season)
    csvs/game_info_{tag}.csv    one row per team per game (date, home/away)

GAME_ID = season code + '9' + ESPN event id (e.g. 2269401810946), so ids never collide with NBA ones and
today's schedule (predict_today.schedule_from_espn) uses the same ids. ESPN players are matched to NBA
PLAYER_IDs by name (team breaks ties) and remembered in csvs/espn_players.csv; anyone new to the league
gets 9_000_000_000 + ESPN id. Edit that file to fix a match.

    python pull_box_scores_espn.py                          # current season: every finished game not yet saved
    python pull_box_scores_espn.py --dates 2026-03-30 --out /tmp/x    # specific dates, elsewhere (testing)
"""
import argparse
import sys
import datetime as dt
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from config import CSV_DIR, DATA
from name_map import norm

ET = ZoneInfo('America/New_York')
API = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
MAP_FILE = CSV_DIR / 'espn_players.csv'
NEW_PLAYER_BASE = 9_000_000_000


def season_of(day):
    y = day.year if day.month >= 8 else day.year - 1
    return f'{y}-{(y + 1) % 100:02d}'


def get(url, **params):
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):        # ValueError: an empty or non-JSON reply
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def finished_games(day):
    """ESPN event ids of finished regular-season games on an ET date."""
    sb = get(f'{API}/scoreboard', dates=day.strftime('%Y%m%d'))
    return [e['id'] for e in sb.get('events', [])
            if e.get('season', {}).get('type') == 2 and e['status']['type'].get('completed')]


def teams_lookup():
    """NBA TEAM_ID, city and nickname by nickname, from the existing box scores."""
    g = pd.read_parquet(DATA / 'player_games.parquet', columns=['TEAM_ID', 'teamCity', 'teamName'])
    return g.drop_duplicates('teamName').set_index('teamName')[['TEAM_ID', 'teamCity']].to_dict('index')


class PlayerMatcher:
    """ESPN athlete -> NBA PLAYER_ID: remembered matches first, then name (+ team) against recent rosters."""

    def __init__(self):
        g = pd.read_parquet(DATA / 'player_games.parquet', columns=['PLAYER_ID', 'player_name', 'TEAM_ID', 'GAME_DATE'])
        g = g.sort_values('GAME_DATE').drop_duplicates('PLAYER_ID', keep='last')
        g['key'] = g['player_name'].map(norm)
        self.by_key = g.groupby('key')
        self.known = (pd.read_csv(MAP_FILE).set_index('espn_id')['PLAYER_ID'].to_dict()
                      if MAP_FILE.exists() else {})
        self.new = []

    def __call__(self, espn_id, name, team_id):
        espn_id = int(espn_id)
        if espn_id in self.known:
            return int(self.known[espn_id])
        key = norm(name)
        pid = None
        if key in self.by_key.groups:
            cands = self.by_key.get_group(key)
            if len(cands) == 1:
                pid = int(cands['PLAYER_ID'].iloc[0])
            else:                                        # same name: prefer the one last seen on this team
                same = cands[cands['TEAM_ID'] == team_id]
                pid = int((same if len(same) else cands.tail(1))['PLAYER_ID'].iloc[-1])
        if pid is None:
            pid = NEW_PLAYER_BASE + espn_id
        self.known[espn_id] = pid
        self.new.append({'espn_id': espn_id, 'PLAYER_ID': pid, 'name': name,
                         'matched': pid < NEW_PLAYER_BASE})
        return pid

    def save(self):
        if not self.new:
            return
        old = pd.read_csv(MAP_FILE) if MAP_FILE.exists() else pd.DataFrame(columns=['espn_id', 'PLAYER_ID', 'name', 'matched'])
        pd.concat([old, pd.DataFrame(self.new)]).drop_duplicates('espn_id').to_csv(MAP_FILE, index=False)


def stat_table(team_block):
    """{espn athlete id: {label: value}} plus starter / DNP info for one team's box score."""
    st = team_block['statistics'][0]
    labels = st.get('labels') or st.get('names')
    out = []
    for a in st['athletes']:
        vals = dict(zip(labels, a.get('stats') or []))
        out.append({'id': a['athlete']['id'], 'name': a['athlete']['displayName'],
                    'first': a['athlete'].get('firstName') or a['athlete']['displayName'].split(' ')[0],
                    'last': a['athlete'].get('lastName') or ' '.join(a['athlete']['displayName'].split(' ')[1:]),
                    'starter': bool(a.get('starter')), 'dnp': bool(a.get('didNotPlay')),
                    'reason': a.get('reason') or '', 'v': vals})
    return out


def made_att(s):
    try:
        m, a = str(s).split('-')
        return int(m), int(a)
    except ValueError:
        return 0, 0


def num(x):
    """A box-score number; ESPN shows '--' (or nothing) for a player who appeared without a recorded stat."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def game_rows(event_id, teams, match):
    s = get(f'{API}/summary', event=event_id)
    comp = s['header']['competitions'][0]
    when = dt.datetime.fromisoformat(comp['date'].replace('Z', '+00:00')).astimezone(ET).date()
    code = '2' + season_of(when)[2:4]
    gid = f'{code}9{event_id}'
    side = {c['team']['id']: c['homeAway'] for c in comp['competitors']}
    abbr = {c['team']['id']: c['team'].get('abbreviation', '') for c in comp['competitors']}
    box, info = [], []
    blocks = s['boxscore']['players']
    for blk in blocks:
        t = blk['team']
        nick = t.get('name') or t['displayName'].split(' ')[-1]
        if nick not in teams:
            raise ValueError(f'unknown ESPN team {t["displayName"]!r}')
        tid, city = teams[nick]['TEAM_ID'], teams[nick]['teamCity']
        opp = [b['team'] for b in blocks if b['team']['id'] != t['id']][0]
        home = side.get(t['id']) == 'home'
        info.append({'GAME_ID': gid, 'TEAM_ID': tid, 'GAME_DATE': str(when),
                     'MATCHUP': f"{abbr.get(t['id'], '')} {'vs.' if home else '@'} {abbr.get(opp['id'], '')}"})
        for p in stat_table(blk):
            v = p['v']
            fgm, fga = made_att(v.get('FG', '0-0'))
            tpm, tpa = made_att(v.get('3PT', '0-0'))
            ftm, fta = made_att(v.get('FT', '0-0'))
            mins = 0 if p['dnp'] else int(num(v.get('MIN')))
            if not p['dnp'] and mins == 0 and v.get('MIN') not in (None, '', '--'):
                mins = 0.5                           # checked in for seconds: ESPN rounds to 0, but he played
            reason = p['reason'].upper()
            comment = "DNP - Coach's Decision" if p['dnp'] and 'COACH' in reason else (p['reason'] if p['dnp'] else '')
            box.append({'GAME_ID': gid, 'TEAM_ID': tid, 'teamCity': city, 'teamName': nick,
                        'PLAYER_ID': match(p['id'], p['name'], tid), 'firstName': p['first'], 'familyName': p['last'],
                        'comment': comment, 'minutes': (f'{int(mins)}:{int(mins % 1 * 60):02d}') if mins else '',
                        'position': 'S' if p['starter'] else '',
                        'points': int(num(v.get('PTS'))), 'fieldGoalsMade': fgm, 'fieldGoalsAttempted': fga,
                        'threePointersMade': tpm, 'threePointersAttempted': tpa,
                        'freeThrowsMade': ftm, 'freeThrowsAttempted': fta,
                        'reboundsOffensive': int(num(v.get('OREB'))), 'reboundsTotal': int(num(v.get('REB'))),
                        'assists': int(num(v.get('AST')))})
    return box, info, when


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dates', nargs='*', help='ET dates to pull (default: season to date, unsaved games only)')
    ap.add_argument('--out', default=str(CSV_DIR), help='folder for the CSVs (testing)')
    args = ap.parse_args()
    out = Path(args.out)
    today = dt.datetime.now(ET).date()
    season = season_of(today - dt.timedelta(days=1))
    tag = str(int(season[:4]) + 1)
    box_path, info_path = out / f'{tag}_all_box.csv', out / f'game_info_{tag}.csv'

    done = set()
    if box_path.exists():
        done = set(pd.read_csv(box_path, usecols=['GAME_ID'], dtype=str)['GAME_ID'])
    if args.dates:
        days = [dt.date.fromisoformat(d) for d in args.dates]
    else:                                   # from the last saved game (or Oct 1) through yesterday
        start = dt.date(int(season[:4]), 10, 1)
        if info_path.exists():
            start = max(start, pd.to_datetime(pd.read_csv(info_path)['GAME_DATE']).max().date() - dt.timedelta(days=2))
        days = [start + dt.timedelta(days=i) for i in range((today - start).days)]

    teams, match = teams_lookup(), PlayerMatcher()
    new_box, new_info, failed = [], [], []
    for day in days:
        try:
            events = finished_games(day)
        except Exception as e:
            failed.append(f'{day} scoreboard: {type(e).__name__}: {e}')
            continue
        for eid in events:
            code = '2' + season_of(day)[2:4]
            if f'{code}9{eid}' in done:
                continue
            try:                                # one game ESPN hasn't finished posting must not lose the others;
                b, i, _ = game_rows(eid, teams, match)   # it isn't saved, so the next run tries it again
            except Exception as e:
                failed.append(f'{day} game {eid}: {type(e).__name__}: {e}')
                continue
            new_box += b
            new_info += i
            time.sleep(0.3)
    match.save()
    if new_box:
        out.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(new_box).to_csv(box_path, mode='a', header=not box_path.exists(), index=False)
        pd.DataFrame(new_info).to_csv(info_path, mode='a', header=not info_path.exists(), index=False)
    unmatched = [n for n in match.new if not n['matched']]
    print(f'{season}: {len(new_info) // 2} new games, {len(new_box)} player rows | new player matches '
          f'{len(match.new)} ({len(unmatched)} not in past rosters: {[u["name"] for u in unmatched][:8]})')
    for f in failed:
        print('skipped (retried next run):', f, file=sys.stderr)
    # Fail only if last night's own download failed: a hiccup re-checking days already saved is harmless
    last_night = [f for f in failed if f.startswith(str(today - dt.timedelta(days=1)))]
    if last_night and not args.dates:
        sys.exit(f'ESPN box scores: last night not fully downloaded ({len(last_night)} failure(s), first: {last_night[0]})')


if __name__ == '__main__':
    main()
