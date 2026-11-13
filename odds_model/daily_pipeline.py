"""The daily run: noon pick, closing line, next-morning settle. Writes the website's data file.

    python daily_pipeline.py picks       # 12:00 ET: noon odds + injury report -> the day's bets (or none)
    python daily_pipeline.py close       # ~10-20 min before a bet's tip (the Worker starts it): closing lines
    python daily_pipeline.py results     # next morning: box scores -> features -> settle the bets

    python daily_pipeline.py picks --set "Luka Doncic=Available"   # override a status (saved), rerun the day
    python daily_pipeline.py remove --set "Daniel Gafford=price moved"   # drop a bet you couldn't get (no rerun)
    python daily_pipeline.py picks --replay --date 2026-03-19     # replay a past day from stored data
    python daily_pipeline.py picks --replay --start 2026-03-01 --end 2026-03-31

The bets follow the backtested rule exactly:
  absences   noon injury report: Out/Doubtful count fully, Questionable half; if the noon report is missing or a
             team has not filed, the previous evening's report; teams on neither fall back to whoever missed their
             previous game. If the NBA hasn't posted a report since 10 AM by noon, the Worker reruns the picks when it appears
             (--late-report; X waits for that run, posting by 3 PM regardless). Manual overrides (data/live/overrides.json, --set) win over all of these
  skip       players on the report (Probable/Questionable/Doubtful) and players on a back-to-back;
             no bets at all from April 1 to the end of the regular season (rotations change, the books know first);
             a team's players in its first 3 games after a player leaves it midseason (roles reshuffle),
             and a traded player until he has played for his new team
  bet        every remaining prop with an edge >= 2%, at the best price among config.BOOKS
  markets    points (both sides), rebounds (unders only), assists (both sides): stat_models.py, backtested
             2023-26 at +7.2% (rebounds unders) and +5.4% (assists) ROI with the same skips
  stake      flat 1u each (the stake the multi-seed backtest validated; size the unit for ~3 bets a night)
Outputs: data/site/picks.json (the website reads this), data/bet_log.csv. Replays write under data/replay/.
Credits: about 1 per game at noon + 1 at close for each game with a bet. Failures put an error banner in
picks.json and show a Mac notification.
"""
import argparse
import datetime as dt
import functools
import json
from pathlib import Path
import os
import shutil
import subprocess
import sys
import traceback

import joblib
import numpy as np
import pandas as pd

from config import BOOKS, CLOSE_LINES, DATA, LIVE, LIVE_MARKETS, ROOT, SPORT
from injury_reports import flip_name
from name_map import norm, roster_match
from parse_odds import american_to_decimal, american_to_prob
from predict_today import ET, likely_out, load_schedule, predict_day, season_of

ON_REPORT = {'Probable', 'Questionable', 'Doubtful'}
WEIGHT = {'Out': 1.0, 'Doubtful': 1.0, 'Questionable': 0.5}
MIN_EDGE = 0.02
STAKE = 1.0
REPORT_DIR = DATA / 'injury_reports'
OVERRIDES = DATA / 'live' / 'overrides.json'
REMOVED = DATA / 'live' / 'removed.json'              # {date: {player: why}}: bets taken off by hand (price gone)
STATUSES = {'Available', 'Probable', 'Questionable', 'Doubtful', 'Out'}
LOG_COLS = ['date', 'player', 'PLAYER_ID', 'team', 'opponent', 'event_id', 'commence_time', 'side', 'line', 'price',
            'book', 'p_side', 'edge', 'stake', 'close_line', 'close_novig_side', 'clv', 'points', 'result', 'units', 'market']
STAT_MARKETS = {'rebounds': 'reb', 'assists': 'ast'}          # besides points; 'points' in the log = the stat's actual value
CORRECTED = DATA / 'live' / 'corrected_bets.csv'               # site-only: stat-market picks re-made after a model fix, by date
X_ADDED_DATES = {'2026-11-08'}                                  # days X also reports the corrected picks for ('added' = not posted at noon)


class OverrideError(ValueError):
    pass


class Paths:
    def __init__(self, replay):
        root = (DATA / os.environ.get('BB_REPLAY_DIR', 'replay')) if replay else DATA
        self.site = root / 'site'
        self.log = root / 'bet_log.csv'
        self.site.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- injury report

def fetch_report(ts, path, allow_fetch):
    if path.exists():
        return pd.read_csv(path)
    if not allow_fetch:
        return None
    from pull_injury_reports import fetch            # starts Java; only when actually needed
    return fetch(ts, path)


EARLY = 10                                       # a same-day report from before 10 AM ET is stale by noon


def noon_report(day, now, allow_fetch):
    """(report, kind): the newest same-day report up to now. At the noon run that is the noon report ('noon', what the
    backtest used); before 10 AM it is stale ('early': the NBA stopped updating overnight); a rerun after noon uses
    the newest one ('late'). Each is cached under its own time, so a later rerun still finds a newer one."""
    noon = dt.datetime(day.year, day.month, day.day, 12, 0)
    if not allow_fetch:
        return fetch_report(None, REPORT_DIR / f'{day}_noon.csv', False), 'noon'
    ts = max(min(now.replace(tzinfo=None), dt.datetime(day.year, day.month, day.day, 23, 45)), noon - dt.timedelta(hours=12))
    ts = ts.replace(minute=ts.minute - ts.minute % 15, second=0, microsecond=0)
    while ts.date() == day:                            # newest first, every 15 min back to midnight
        rep = fetch_report(ts, REPORT_DIR / f"{day}_{'noon' if ts == noon else ts.strftime('%H%M')}.csv", True)
        if rep is not None:
            return rep, 'late' if ts > noon else 'early' if ts.hour < EARLY else 'noon'
        ts -= dt.timedelta(minutes=15)
    return None, None


def tidy(rep, day):
    rep = rep[pd.to_datetime(rep['Game Date'], format='%m/%d/%Y', errors='coerce') == pd.Timestamp(day)].copy()
    rep['Team'] = rep['Team'].ffill()
    rep['not_submitted'] = rep['Reason'].astype(str).str.contains('NOT YET SUBMITTED')
    return rep


def load_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def remove_bets(paths, text):
    """Take bets off today's page and record by hand (the price is gone), without rerunning the odds.
    'Daniel Gafford=price moved, ...'; saved so a later rerun keeps them off."""
    site = json.loads((paths.site / 'picks.json').read_text())
    want = {n.strip(): (w.strip() or 'price moved') for n, _, w in
            (x.partition('=') for x in text.replace(';', ',').split(',') if x.strip())}
    bets = {norm(p['player']): p['player'] for p in site.get('picks', [])}
    hit = {bets[norm(n)]: w for n, w in want.items() if norm(n) in bets}
    if missing := [n for n in want if norm(n) not in bets]:
        raise OverrideError(f"not one of today's bets: {missing} (bets: {list(bets.values())})")
    site['picks'] = [p for p in site['picks'] if p['player'] not in hit]
    for r in site.get('board', []):
        if r['player'] in hit:
            r.update(play='skip', why=f'Removed by hand ({hit[r["player"]]})', stake=None)
    for r in site.get('props', []):
        if r['player'] in hit:
            r['skip'] = f'removed by hand ({hit[r["player"]]})'
    log = read_log(paths)
    log[~((log['date'].astype(str) == site['date']) & log['player'].isin(hit))].to_csv(paths.log, index=False)
    allx = load_json(REMOVED)
    allx[site['date']] = {**allx.get(site['date'], {}), **hit}
    REMOVED.write_text(json.dumps(allx, indent=1, sort_keys=True) + '\n')
    write_site(paths, site)
    return f"removed {', '.join(hit)} from {site['date']}; bets now: {[p['player'] for p in site['picks']] or 'none'}"


def load_overrides(day):
    try:
        return json.loads(OVERRIDES.read_text()).get(str(day), {})
    except FileNotFoundError:
        return {}


def parse_overrides(text):
    """'Luka Doncic=Available, Jaxson Hayes=Out' -> {name: status}."""
    new = {}
    for part in filter(None, (x.strip() for x in text.replace(';', ',').split(','))):
        name, _, st = part.partition('=')
        st = {'Active': 'Available', 'Playing': 'Available'}.get(st.strip().title(), st.strip().title())
        if not name.strip() or st not in STATUSES:
            raise OverrideError(f'bad override {part!r}: use "Player Name=Status", status one of {sorted(STATUSES)}')
        new[name.strip()] = st
    return new


def save_overrides(day, over):
    """Kept so later reruns of the day (and the record) use them too."""
    allx = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    allx[str(day)] = over
    OVERRIDES.write_text(json.dumps(allx, indent=1, sort_keys=True) + '\n')


def apply_overrides(weights, status, roster, teams, over):
    """Your statuses replace the report's (or the previous-game guess) for those players."""
    cand = roster[roster['TEAM_ID'].isin(teams)]
    for name, st in over.items():
        exact = cand[cand['key'] == norm(name)]
        pid = exact['PLAYER_ID'].iloc[0] if len(exact) == 1 else roster_match(norm(name), cand)
        if pid is None or pd.isna(pid):
            raise OverrideError(f'override: no player named {name!r} on tonight\'s teams')
        pid = int(pid)
        status = status[status['PLAYER_ID'] != pid]
        weights.pop(pid, None)
        if st != 'Available':
            r = cand[cand['PLAYER_ID'] == pid].iloc[0]
            status = pd.concat([status, pd.DataFrame([{'TEAM_ID': r['TEAM_ID'], 'name': r['player_name'], 'status': st,
                                                       'source': 'manual', 'PLAYER_ID': pid}])], ignore_index=True)
            if st in WEIGHT:
                weights[pid] = WEIGHT[st]
        print(f'override: {cand.loc[cand["PLAYER_ID"] == pid, "player_name"].iloc[0]} -> {st}', flush=True)
    return weights, status


def injury_weights(games, day, schedule, now, allow_fetch, over=None, late=False):
    """{PLAYER_ID: weight}, per-player status table, and where each team's info came from."""
    season = season_of(day)
    cur = games[(games['season'] == season) & (games['GAME_DATE'] < pd.Timestamp(day))]
    nick = cur.drop_duplicates('TEAM_ID').set_index('teamName')['TEAM_ID']
    team_id = lambda t: next((nick[n] for n in nick.index if str(t).endswith(n)), None)
    roster = cur.drop_duplicates(['TEAM_ID', 'PLAYER_ID'])[['TEAM_ID', 'PLAYER_ID', 'player_name']].copy()
    roster['key'] = roster['player_name'].map(norm)
    teams = set(schedule['TEAM_ID'])

    sources, rows = {}, []
    noon, kind = noon_report(day, now, allow_fetch)
    reports = [(f'{kind} report', tidy(noon, day))] if noon is not None else []
    if noon is None or reports[0][1]['not_submitted'].any():
        prev = day - dt.timedelta(days=1)
        path = REPORT_DIR / f'{day}_prevday.csv'
        last = dt.datetime(prev.year, prev.month, prev.day, 23, 45)
        for back in range(0, 6 * 60 + 46, 15):         # latest first: 11:45 PM back to 5:00 PM
            r = fetch_report(last - dt.timedelta(minutes=back), path, allow_fetch)
            if r is not None:
                reports.append(('previous evening', tidy(r, day)))
                break
    for source, rep in reports:
        rep['TEAM_ID'] = rep['Team'].map(team_id)
        filed = set(rep.loc[~rep['not_submitted'], 'TEAM_ID'].dropna()) & teams - set(sources)
        for t in filed:
            sources[t] = source
            listed = rep[(rep['TEAM_ID'] == t) & rep['Player Name'].notna() & ~rep['not_submitted']]
            rows += [{'TEAM_ID': t, 'name': flip_name(n), 'status': s, 'source': source}
                     for n, s in zip(listed['Player Name'], listed['Current Status'])]
    status = pd.DataFrame(rows, columns=['TEAM_ID', 'name', 'status', 'source'])
    pids = []
    for r in status.itertuples():
        cand = roster[roster['TEAM_ID'] == r.TEAM_ID]
        exact = cand[cand['key'] == norm(r.name)]
        pids.append(exact['PLAYER_ID'].iloc[0] if len(exact) == 1 else roster_match(norm(r.name), cand))
    status['PLAYER_ID'] = pids
    unmatched = status[status['PLAYER_ID'].isna()]
    status = status.dropna(subset=['PLAYER_ID']).astype({'PLAYER_ID': int})

    weights = {p: WEIGHT[s] for p, s in zip(status['PLAYER_ID'], status['status']) if s in WEIGHT}
    # Teams with no report: whoever missed their previous game is out (as in the backtest)
    missing = teams - set(sources)
    if missing:
        names = set(likely_out(games, day, schedule[schedule['TEAM_ID'].isin(missing)]))
        prev_out = roster[roster['player_name'].isin(names) & roster['TEAM_ID'].isin(missing)]
        weights.update({p: 1.0 for p in prev_out['PLAYER_ID']})
        sources.update({t: 'previous game' for t in missing})
    if over:
        weights, status = apply_overrides(weights, status, roster, teams, over)
    # report: noon / late; early or missing = no fresh report, so the Worker watches for one; none = gave up (3 PM)
    report = kind or 'missing'
    if late and report in ('early', 'missing'):
        report = 'none'
    return weights, status, sources, list(unmatched['name']), report


# ---------------------------------------------------------------- odds

def pull_noon_odds(refresh=False):
    """Noon snapshot of every game tipping today (1 credit each), parsed to data/live/odds_lines.parquet. A rerun reuses
    the noon snapshot; refresh=True (late injury news moved lines) moves it to odds_live/noon/ and takes a new one."""
    from daily_logger import snapshot
    from odds_api import OddsAPI
    api = OddsAPI()
    now = dt.datetime.now(dt.timezone.utc)
    start = lambda e: dt.datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00'))
    events = [e for e in api.get(f'/sports/{SPORT}/events', expected_cost=0) or []
              if start(e).astimezone(ET).date() == now.astimezone(ET).date() and start(e) > now]
    if refresh:                                     # the parser only reads odds_live/*.json, so noon/ is kept, not read
        (LIVE / 'noon').mkdir(exist_ok=True)
        for e in events:
            old = LIVE / f"{e['id']}_early.json"
            if old.exists():
                old.replace(LIVE / 'noon' / old.name)
    saved = snapshot(api, events, 'early')
    parse_live()
    return f'{len(events)} games, {saved} new snapshots{" (lines refreshed " + now.astimezone(ET).strftime("%-I:%M %p") + ")" if refresh else ""}, credits left {api.remaining}'


def parse_live():
    """data/live/odds_lines.parquet (points) and odds_lines_{rebounds,assists}.parquet from the live snapshots."""
    (DATA / 'live').mkdir(exist_ok=True)
    for market in LIVE_MARKETS:
        r = subprocess.run([sys.executable, str(ROOT / 'parse_odds.py'), '--raw-dir', str(LIVE), '--out-dir', str(DATA / 'live'),
                            '--market', market], capture_output=True, text=True)
        if r.returncode != 0 and market == 'player_points':      # points must parse; a missing other market isn't fatal
            raise RuntimeError('parse_odds failed: ' + (r.stderr or r.stdout)[-300:])


# ---------------------------------------------------------------- the pick

def season_end(day):
    """April 1 through the end of the regular season (about its last two weeks): teams rest starters and tank, bench
    players' lines jump with their minutes, and the model's unders lost in two of three backtest Aprils, with the
    closing line against it in all three."""
    return day.month in (4, 5, 6)


LEFT_TEAM_GAMES = 3
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'


def espn_rosters(day):
    """{team nickname: [normalized names]} for teams playing on `day`, from ESPN's current rosters ({} if ESPN fails)."""
    import requests
    out = {}
    try:
        sb = requests.get(f'{ESPN}/scoreboard', params={'dates': day.strftime('%Y%m%d')}, timeout=30).json()
        for e in sb.get('events', []):
            for c in e['competitions'][0]['competitors']:
                t = c['team']
                r = requests.get(f"{ESPN}/teams/{t['id']}/roster", timeout=30).json()
                ath = [x for a in r.get('athletes', []) for x in (a.get('items') or [a])]
                names = [x.get('fullName') or x.get('displayName') for x in ath]
                if len(names) >= 10:
                    out[t.get('name') or t['displayName'].split(' ')[-1]] = [norm(n) for n in names if n]
    except Exception as e:
        print(f'ESPN rosters failed ({type(e).__name__}); using box scores only for departures')
    return out


def left_behind(games, day, rosters=None):
    """{team nickname: n} for teams in their first 3 games (n played so far) after a player left them midseason.
    The rest of the roster's roles reshuffle and the books adjust first: in the backtest those bets won 42%.
    A departure is a player whose latest box score this season is for another team, or (live) who played for the
    team this season but is missing from its current ESPN roster (a trade is known before he plays again)."""
    season = season_of(day)
    p = games[games['played'] & (games['season'] == season) & (games['GAME_DATE'] < pd.Timestamp(day))].sort_values('GAME_DATE')
    if p.empty:
        return {}
    last = p.groupby(['PLAYER_ID', 'teamName'])['GAME_DATE'].max().reset_index()
    latest = last['PLAYER_ID'].map(p.groupby('PLAYER_ID')['teamName'].last())
    deps = list(zip(last.loc[last['teamName'] != latest, 'teamName'], last.loc[last['teamName'] != latest, 'GAME_DATE']))
    names = p.groupby('PLAYER_ID')['player_name'].last()
    for team, keys in (rosters or {}).items():
        cand = pd.DataFrame({'key': keys, 'PLAYER_ID': range(len(keys))})
        cur = last[(last['teamName'] == team) & (latest == team)]
        miss = [(team, d) for pid, d in zip(cur['PLAYER_ID'], cur['GAME_DATE'])
                if norm(names[pid]) not in keys and roster_match(norm(names[pid]), cand) is None]
        if len(miss) <= 3:                               # more looks like a name or data problem, not trades
            deps += miss
    tg = p.drop_duplicates(['teamName', 'GAME_ID'])
    out = {}
    for team, left in deps:
        n = int(((tg['teamName'] == team) & (tg['GAME_DATE'] > left)).sum())
        if n < LEFT_TEAM_GAMES:
            out[team] = min(n, out.get(team, n))
    return out


def on_other_team(b):
    """The prop's game doesn't include the team in his box scores: traded, not yet played for the new team (the
    projection would use the old team's context), or a name mix-up."""
    if 'home_team' not in b or 'away_team' not in b:
        return pd.Series(False, index=b.index)
    return [isinstance(h, str) and not (h.endswith(t) or str(a).endswith(t)) for t, h, a in zip(b['team'], b['home_team'], b['away_team'])]


def make_board(f, status, day, left=None, removed=None):
    """Every prop with a line, scored, with what the rule does with it."""
    b = f.dropna(subset=['early_line', 'p_over']).copy()
    st = status.drop_duplicates('PLAYER_ID').set_index('PLAYER_ID')['status']
    b['status'] = b['PLAYER_ID'].map(st)
    b['side'] = np.where(b['edge_over'] >= b['edge_under'], 'OVER', 'UNDER') if 'edge_over' in b else \
        np.where(b['p_over'] - american_to_prob(b['early_best_over_price'])
                 >= (1 - b['p_over']) - american_to_prob(b['early_best_under_price']), 'OVER', 'UNDER')
    over = b['side'] == 'OVER'
    b['price'] = np.where(over, b['early_best_over_price'], b['early_best_under_price'])
    b['book'] = np.where(over, b['early_best_over_book'], b['early_best_under_book'])
    b['p_side'] = np.where(over, b['p_over'], 1 - b['p_over'])
    gone = b['team'].map(left or {})
    by_hand = b['player_name'].map(removed or {})
    b['skip'] = np.select([by_hand.notna(), np.full(len(b), season_end(day)), np.asarray(on_other_team(b), dtype=bool), gone.notna(),
                           b['status'].isin(ON_REPORT), b['rest_days'] == 1],
                          ['removed by hand (' + by_hand.fillna('').astype(str) + ')', 'last two weeks of the season',
                           'new team, no games yet',
                           'teammate traded (game ' + (gone.fillna(0) + 1).astype(int).astype(str) + ' of 3 since)',
                           'on injury report (' + b['status'].fillna('') + ')', 'back-to-back'], '')
    bet = (b['skip'] == '') & (b['edge'] >= MIN_EDGE)
    b['play'] = np.where(b['skip'] != '', 'skip: ' + b['skip'], np.where(bet, 'BET ' + b['side'] + f' {STAKE:g}u',
                                                                          'pass: edge < 2%'))
    b['stake'] = np.where(bet, STAKE, np.nan)
    b = b.sort_values('edge', ascending=False)
    return b, list(b.index[bet.reindex(b.index)])


def run_picks(day, paths, replay, now, extra=None, late=False, refresh=False):
    games = pd.read_parquet(DATA / 'player_games.parquet')
    schedule = load_schedule(games, day, from_history=replay)
    site = {'date': str(day), 'updated': now.strftime('%Y-%m-%d %I:%M %p ET'), 'status': 'ok', 'message': '',
            'picks': [], 'board': [], 'injuries': [], 'games': [], 'slate': {}}
    if schedule.empty:
        site['message'] = 'No games today.'
        return site
    odds_note = 'replay: historical noon lines' if replay else pull_noon_odds(refresh)
    over = {} if replay else {**load_overrides(day), **(extra or {})}
    weights, status, sources, unmatched, report = injury_weights(games, day, schedule, now, allow_fetch=not replay,
                                                                 over=over, late=late)
    om = joblib.load(DATA / 'models' / 'over_model.pkl')
    try:
        f = predict_day(games, day, schedule, out_weights=weights)
    except ValueError as e:                     # first night of a season: nothing to project from yet
        site['message'] = str(e)
        return site
    if 'p_over' not in f:
        site['status'], site['message'] = 'error', 'No noon lines were found for today\'s games.'
        return site
    left = left_behind(games, day, None if replay else espn_rosters(day))
    removed = {} if replay else load_json(REMOVED).get(str(day), {})
    board, bet_idx = make_board(f, status, day, left, removed)

    site.update(slate_payload(schedule, board, f, status, sources, unmatched, odds_note, games, day))
    site['slate']['overrides'] = over
    site['slate']['report'] = report            # noon / late / early or missing (the Worker reruns when one appears) / none
    site['props'] = props_payload(board)
    site['model'] = model_payload(om)
    site['roster'] = roster_payload(games, day, schedule, weights, status, export_model(paths))
    check_browser_model(paths, site, f)
    to_bet = [(board, i) for i in bet_idx]
    site['markets'] = {}
    boards, sx, sproj = stat_boards(games, day, schedule, weights, status, replay, left, removed)
    if sx is not None:
        stat_roster(site['roster'], sx, export_stat_model(paths))
        check_stat_model(paths, site, sproj, boards)
    for market, (mb, midx) in boards.items():
        site['markets'][market] = {'board': [row_payload(r) for _, r in mb.head(15).iterrows()], 'n_props': int(len(mb)),
                                   'n_eligible': int((mb['skip'] == '').sum()), 'bets': len(midx),
                                   'props': stat_props_payload(mb)}
        to_bet += [(mb, i) for i in midx]
    bets = []
    for src, i in to_bet:
        p = src.loc[i]
        bet = {'date': str(day), 'player': p['player_name'], 'PLAYER_ID': int(p['PLAYER_ID']), 'team': abbr(p['team']),
               'opponent': abbr(team_names().get(p['OPP_ID'], '')), 'event_id': p.get('event_id'),
               'commence_time': p.get('commence_time'), 'side': p['side'], 'line': float(p['early_line']),
               'price': int(p['price']), 'book': BOOK_NAMES.get(p['book'], p['book']), 'p_side': round(float(p['p_side']), 4),
               'edge': round(float(p['edge']), 4), 'stake': float(p['stake']), 'market': p.get('market', 'points')}
        site['picks'].append({**bet, **row_payload(p), 'books': book_prices(p, replay, bet['market']),
                              'link': link(p.get('early_best_over_link' if p['side'] == 'OVER' else 'early_best_under_link'))})
        if replay and pd.notna(p.get('close_line')):        # replays know the close already
            over = p['side'] == 'OVER'
            bet['close_line'] = float(p['close_line'])
            bet['close_novig_side'] = float(p['close_novig_over'] if over else 1 - p['close_novig_over'])
            bet['clv'] = (bet['close_line'] - bet['line']) * (1 if over else -1)
        bets.append(bet)
    if refresh and not replay:
        # A line refresh after the day's bets are out: those bets stay the record (they were posted and placed). Each is
        # tagged with how it looks at the new odds; the board shows the new lines. Nothing new is logged.
        prev = load_json(paths.site / 'picks.json')
        if prev.get('date') == str(day) and prev.get('picks'):
            key = lambda p: (p['player'], p.get('market', 'points'), p['side'])
            fresh, at = {key(p): p for p in site['picks']}, now.strftime('%-I:%M %p')
            for p in prev['picks']:
                f = fresh.get(key(p))
                p['now'] = {'at': at, 'valid': f is not None,
                            **({k: f[k] for k in ('side', 'line', 'price', 'book', 'edge')} if f else {})}
            site['picks'], site['message'] = prev['picks'], ''
            return site
    log_bets(paths, str(day), bets)
    if not bets and season_end(day):
        site['message'] = ('No bets: the site sits out April 1 to the end of the regular season, when teams rest '
                           'starters and rotations change faster than the model can follow.')
    elif not bets:
        top = board[board['skip'] == '']
        best = f"{top['edge'].iloc[0]:+.1%}" if len(top) else 'n/a'
        site['message'] = f'No bets today: the best eligible edge is {best}, below the 2% minimum.'
    return site


TEAM_ABBR = {'Hawks': 'ATL', 'Celtics': 'BOS', 'Nets': 'BKN', 'Hornets': 'CHA', 'Bulls': 'CHI', 'Cavaliers': 'CLE',
             'Mavericks': 'DAL', 'Nuggets': 'DEN', 'Pistons': 'DET', 'Warriors': 'GSW', 'Rockets': 'HOU', 'Pacers': 'IND',
             'Clippers': 'LAC', 'Lakers': 'LAL', 'Grizzlies': 'MEM', 'Heat': 'MIA', 'Bucks': 'MIL', 'Timberwolves': 'MIN',
             'Pelicans': 'NOP', 'Knicks': 'NYK', 'Thunder': 'OKC', 'Magic': 'ORL', '76ers': 'PHI', 'Suns': 'PHX',
             'Trail Blazers': 'POR', 'Kings': 'SAC', 'Spurs': 'SAS', 'Raptors': 'TOR', 'Jazz': 'UTA', 'Wizards': 'WAS'}
BOOK_NAMES = {'draftkings': 'DraftKings', 'fanduel': 'FanDuel', 'betmgm': 'BetMGM', 'williamhill_us': 'Caesars'}


@functools.cache
def team_names():
    """TEAM_ID -> name, from the box scores. Read on first use: close runs skip build_features, so the file isn't there."""
    return pd.read_parquet(DATA / 'player_games.parquet', columns=['TEAM_ID', 'teamName']) \
        .drop_duplicates('TEAM_ID').set_index('TEAM_ID')['teamName'].to_dict()


abbr = lambda name: TEAM_ABBR.get(name, name)


def row_payload(r):
    """One prop as the website shows it."""
    kind, _, why = r['play'].partition(': ')
    kind = 'bet' if kind.startswith('BET') else kind
    return {'player': r['player_name'], 'team': abbr(r['team']), 'opp': abbr(team_names().get(r['OPP_ID'], '')),
            'side': r['side'], 'line': float(r['early_line']), 'price': int(r['price']),
            'book': BOOK_NAMES.get(r['book'], r['book']), 'mkt': round(float(r['early_novig_over']), 4),
            'proj': round(float(r['pred_points']), 1), 'sigma': round(float(r['pred_sd']), 1),
            'p': round(float(r['p_side']), 4), 'be': round(float(american_to_prob(r['price'])), 4),
            'edge': round(float(r['edge']), 4), 'season': round(float(r['pts_season']), 1),
            'last5': None if pd.isna(r['pts_5']) else round(float(r['pts_5']), 1), 'play': kind,
            'why': why.replace('on injury report (', '').rstrip(')').capitalize() if kind == 'skip' else
                   ('edge under 2%' if 'edge' in why else ''), 'stake': None if pd.isna(r.get('stake')) else float(r['stake'])}


def link(v):
    """A sportsbook bet-slip link, or None (historical snapshots have none)."""
    return v if isinstance(v, str) and v.startswith('http') else None


def props_payload(board):
    """Every prop with what the browser needs to re-project it from a different minutes estimate."""
    out = []
    for _, r in board.iterrows():
        out.append({'player': r['player_name'], 'id': int(r['PLAYER_ID']), 'team': abbr(r['team']),
                    'opp': abbr(team_names().get(r['OPP_ID'], '')), 'line': float(r['early_line']),
                    'mkt': round(float(r['early_novig_over']), 4), 'proj': round(float(r['pred_points']), 2),
                    'min': round(float(r['pred_minutes']), 1), 'gp': int(r['gp']), 'skip': r['skip'],
                    'season': round(float(r['pts_season']), 1),
                    'over': [int(r['early_best_over_price']), BOOK_NAMES.get(r['early_best_over_book'], r['early_best_over_book']),
                             link(r.get('early_best_over_link'))],
                    'under': [int(r['early_best_under_price']), BOOK_NAMES.get(r['early_best_under_book'], r['early_best_under_book']),
                              link(r.get('early_best_under_link'))]})
    return out


BROWSER_COLS = ['pts_season', 'min_season', 'fga_season', 'team_fga_pg', 'out_fga_season_avg', 'out_fga_5', 'ret_mpg']


def trees(model):
    """A LightGBM model as nested lists: [feature, threshold, defaultLeft, missingIsNaN, left, right] or a leaf."""
    d = model.booster_.dump_model()
    def node(n):
        if 'leaf_value' in n:
            return n['leaf_value']
        return [n['split_feature'], n['threshold'], int(n['default_left']), int(n['missing_type'] == 'NaN'),
                node(n['left_child']), node(n['right_child'])]
    return {'features': d['feature_names'], 'trees': [node(t['tree_structure']) for t in d['tree_info']]}


def export_model(paths):
    """The minutes and points models as compact trees for site/model.js (written next to picks.json)."""
    pm = joblib.load(DATA / 'models' / 'points_model.pkl')
    cols = list(dict.fromkeys(pm['minutes_features'] + [c for c in pm['features'] if c != 'pred_minutes'] + BROWSER_COLS))
    out = {'trained_through': pm['trained_through'], 'columns': cols, 'damping': list(pm['damping']),
           'minutes': trees(pm['minutes_model']), 'points': trees(pm['model'])}
    (paths.site / 'model.json').write_text(json.dumps(out, separators=(',', ':')))
    return cols


def check_browser_model(paths, site, f):
    """site/model.js must reproduce today's Python projections (within 0.01) or nothing is published."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'history').mkdir()
        shutil.copy(paths.site / 'model.json', tmp / 'model.json')
        (tmp / 'history' / f"{site['date']}.json").write_text(json.dumps({'roster': site['roster']}))
        exp = {site['date']: {int(i): [float(a), float(m)] for i, a, m in zip(f['PLAYER_ID'], f['pred_points'], f['pred_minutes'])}}
        (tmp / 'expected.json').write_text(json.dumps(exp))
        r = subprocess.run(['node', str(ROOT / 'test_browser_model.js'), str(tmp), str(tmp / 'expected.json')],
                           capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError('browser model does not match Python: ' + (r.stdout or r.stderr)[-300:])


# Built in the browser from the lineup (model.js statTeamProjections); everything else comes from the roster
STAT_LINEUP = {'pred_minutes', 'out_min', 'n_out', 'out_reb', 'out_ast', 'out_reb_pos', 'out_ast_pos', 'new_out_reb',
               'new_out_ast', 'new_out_reb_pos', 'new_out_ast_pos', 'exp_extra_reb', 'exp_extra_ast',
               'out_min_pos', 'n_active_pos', 'pos_vacancy', 'ret_min', 'ret_min_pos'}   # last five: model.js withAbsences
STAT_HELPERS = ['reb_out_avg', 'ast_out_avg', 'out_reb_usual', 'out_ast_usual', 'out_reb_pos_usual', 'out_ast_pos_usual',
                'reb_season', 'ast_season', 'team_reb', 'team_ast', 'reb_5', 'ast_5']


def export_stat_model(paths):
    """The rebounds and assists models for model.js: trees, count dispersion, P(over) weights (stat_model.json)."""
    import stat_models as SM
    sm = joblib.load(SM.MODEL_PATH)
    markets = {m: {'key': STAT_MARKETS[m], 'features': sm[m]['features'], 'edges': [float(v) for v in sm[m]['edges']],
                   'rs': [float(v) for v in sm[m]['rs']], 'clf_cols': sm[m]['clf_cols'], 'clf_b': sm[m]['clf_b'],
                   'sides': list(sm[m]['sides']), **trees(sm[m]['model'])} for m in STAT_MARKETS if m in sm}
    feats = [f for m in markets.values() for f in m['features'] if f not in STAT_LINEUP]
    cols = list(dict.fromkeys(feats + STAT_HELPERS))
    (paths.site / 'stat_model.json').write_text(json.dumps(
        {'trained_through': sm['trained_through'], 'columns': cols, 'markets': markets}, separators=(',', ':')))
    return cols


def stat_roster(roster, x, cols):
    """Each roster player's rebounds/assists inputs ('s', in stat_model.json column order) and position group."""
    by = x.drop_duplicates('PLAYER_ID').set_index('PLAYER_ID')
    for players in roster.values():
        for c in players:
            if c['id'] in by.index:
                r = by.loc[c['id']]
                c['s'] = [None if pd.isna(r[k]) else float(r[k]) for k in cols]
                c['spos'] = None if pd.isna(r['pos']) else str(r['pos'])
                c['rpg'], c['apg'] = round(float(r['reb_out_avg']), 1), round(float(r['ast_out_avg']), 1)


def check_stat_model(paths, site, proj, boards):
    """model.js must reproduce tonight's Python rebounds/assists projections and P(over) or nothing is published."""
    import tempfile
    exp = {'proj': {m: {int(i): float(v) for i, v in zip(y['PLAYER_ID'], y['proj'])} for m, y in proj.items()},
           'props': {m: [[int(r['PLAYER_ID']), float(r['early_line']), float(r['early_novig_over']), float(r['p_over'])]
                         for _, r in b.iterrows()] for m, (b, _) in boards.items()}}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for f in ['model.json', 'stat_model.json']:
            shutil.copy(paths.site / f, tmp / f)
        (tmp / 'day.json').write_text(json.dumps({'roster': site['roster']}))
        (tmp / 'expected.json').write_text(json.dumps(exp))
        r = subprocess.run(['node', str(ROOT / 'test_browser_stats.js'), str(tmp)], capture_output=True, text=True, cwd=ROOT)
    print(r.stdout.strip())
    if r.returncode != 0:
        raise RuntimeError('browser rebounds/assists model does not match Python: ' + (r.stdout or r.stderr)[-300:])


def stat_props_payload(board):
    """props_payload plus what the stat pages show: last five, the count model's spread."""
    out = props_payload(board)
    for o, (_, r) in zip(out, board.iterrows()):
        o['mkt'] = round(float(r['early_novig_over']), 6)
        o['last5'] = None if pd.isna(r['pts_5']) else round(float(r['pts_5']), 1)
        o['sd'] = round(float(r['pred_sd']), 2)
    return out


def roster_payload(games, day, schedule, weights, status, cols):
    """Every rostered player on tonight's teams: reported weight, status and pre-game inputs for model.js."""
    st = status.drop_duplicates('PLAYER_ID').set_index('PLAYER_ID')['status']
    fa = predict_day.__globals__['features_as_of'](games, day, schedule, [], weights, keep_out=True)
    teams = {}
    for _, r in fa.sort_values('min_season', ascending=False).iterrows():
        pid = int(r['PLAYER_ID'])
        label = st.get(pid) if st.get(pid) in ('Out', 'Doubtful', 'Questionable', 'Probable') else \
            ('Missed last game' if weights.get(pid, 0) >= 1 else '')
        vals = [None if pd.isna(r[c]) else float(r[c]) for c in cols]
        teams.setdefault(abbr(r['team']), []).append({
            'id': pid, 'name': r['player_name'], 'status': label, 'w': float(weights.get(pid, 0.0)),
            'ppg': round(float(r['pts_season']), 1), 'mpg': round(float(r['min_season']), 1), 'f': vals})
    return teams


def model_payload(om):
    """Classifier coefficients, stake scale and the projection-uncertainty table (for in-browser re-projection)."""
    pm = joblib.load(DATA / 'models' / 'points_model.pkl')
    return {'b0': om['b0'], 'b_gap': om['b_gap'], 'b_z': om['b_z'], 'stake': STAKE, 'min_edge': MIN_EDGE,
            'sd_cuts': [round(float(x), 3) for x in pm['bins'][1:-1]], 'sd': [round(float(x), 3) for x in pm['sd']]}


def stat_lines(market, day, replay):
    """The day's noon lines for a stat market: the live log, else the historical pull (replays)."""
    for path in ([] if replay else [DATA / 'live' / f'odds_lines_{market}.parquet']) + [DATA / f'odds_lines_{market}.parquet']:
        if path.exists():
            x = pd.read_parquet(path)
            x = x[pd.to_datetime(x['commence_time'], utc=True).dt.tz_convert(ET).dt.date == day]
            if not x.empty:
                return x
    return pd.DataFrame()


def stat_boards(games, day, schedule, weights, status, replay, left, removed):
    """{market: (board, bet indexes)} for rebounds and assists, through the same make_board skips as points."""
    import stat_models as SM
    from predict_today import features_as_of, project
    if not SM.MODEL_PATH.exists():
        return {}, None, {}
    sm = joblib.load(SM.MODEL_PATH)
    lines = {m: stat_lines(m, day, replay) for m in STAT_MARKETS}
    if all(l.empty for l in lines.values()):
        return {}, None, {}
    fa = project(features_as_of(games, day, schedule, [], weights, keep_out=True), joblib.load(DATA / 'models' / 'points_model.pkl'))
    x = SM.tonight_inputs(games, day, fa, weights, keep_out=True)
    out, proj = {}, SM.project_tonight(x, sm)
    for market, y in proj.items():
        d = SM.score_props(y, lines[market], sm[market])
        if d.empty:
            continue
        key = STAT_MARKETS[market]
        d = d.assign(pred_points=d['proj'], pts_season=d[f'{key}_season'], pts_5=d[f'{key}_5'], market=market)
        out[market] = make_board(d, status, day, left, removed)
    return out, x, proj


def book_prices(p, replay, market='points'):
    """Every book's noon price for the pick's side, scored against the same model probability."""
    sfx = '' if market == 'points' else f'_{market}'
    path = DATA / (f'odds_books{sfx}.parquet' if replay else f'live/odds_books{sfx}.parquet')
    if not path.exists():
        return []
    b = pd.read_parquet(path)
    b = b[(b['snapshot'] == 'early') & (b['event_id'] == p['event_id']) & (b['player'].map(norm) == norm(p['player_name']))]
    over = p['side'] == 'OVER'
    out = []
    for r in b.itertuples():
        price = int(r.over_price if over else r.under_price)
        be = float(american_to_prob(price))
        out.append({'book': BOOK_NAMES.get(r.book, r.book), 'line': float(r.point), 'price': price, 'be': round(be, 4),
                    'link': link(getattr(r, 'over_link' if over else 'under_link', None)),
                    'edge': round(float(p['p_side']) - be, 4) if r.point == p['early_line'] else None})
    return sorted(out, key=lambda x: -999 if x['edge'] is None else -x['edge'])


def b2b_teams(games, day, schedule):
    """Teams on `schedule` that also played the day before (yesterday's box scores, or its cached schedule if a box
    score is missing): the second night of a back-to-back, whose players the rule skips."""
    prev = day - dt.timedelta(days=1)
    played = set(games.loc[games['GAME_DATE'] == pd.Timestamp(prev), 'TEAM_ID'].astype(int))
    cache = DATA / 'schedules' / f'{prev}.csv'
    if cache.exists():
        played |= set(pd.read_csv(cache)['TEAM_ID'].astype(int))
    return set(schedule['TEAM_ID'].astype(int)) & played


def game_rows(schedule, day, games, tip):
    """One row per game, by tip time. tip(home_id, away_id) -> UTC/ET timestamp or None. 'b2b': the teams on a back-to-back
    (the pages leave them out). 'ids' is for the caller and is popped before publishing."""
    b2b, gm = b2b_teams(games, day, schedule), []
    for gid, g in schedule.groupby('GAME_ID'):
        h, a = g.loc[g['is_home'] == 1, 'TEAM_ID'], g.loc[g['is_home'] == 0, 'TEAM_ID']
        if h.empty or a.empty:
            continue
        home, away = int(h.iloc[0]), int(a.iloc[0])
        t = tip(home, away)
        t = pd.Timestamp(t).tz_convert(ET) if t is not None else None
        gm.append({'home': abbr(team_names().get(home, '')), 'away': abbr(team_names().get(away, '')),
                   'tip': t.strftime('%-I:%M %p ET') if t is not None else '', 't': t.isoformat() if t is not None else '',
                   'b2b': [abbr(team_names().get(x, '')) for x in (away, home) if x in b2b], 'ids': (home, away)})
    gm.sort(key=lambda x: x['t'])
    return gm


def espn_tips(day):
    """{(home, away) team names: tip time (UTC)} from ESPN's scoreboard."""
    import requests
    sb = requests.get('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard',
                      params={'dates': day.strftime('%Y%m%d')}, timeout=30).json()
    out = {}
    for e in sb.get('events', []):
        side = {c['homeAway']: c['team'].get('name') or c['team']['displayName'].split(' ')[-1]
                for c in e['competitions'][0]['competitors']}
        out[(side.get('home'), side.get('away'))] = pd.Timestamp(e['date'])
    return out


def tonight_payload(games, day):
    """The morning page's look ahead: tonight's games, before the noon run replaces them with the full slate."""
    schedule = load_schedule(games, day)
    if schedule.empty:
        return {'date': str(day), 'games': []}
    try:
        tips = espn_tips(day)
    except Exception as e:                            # tip times are a nicety; the games still show
        print(f'tonight: no ESPN tip times ({type(e).__name__})')
        tips = {}
    name = team_names()
    gm = game_rows(schedule, day, games, lambda h, a: tips.get((name.get(h), name.get(a))))
    for g in gm:
        g.pop('ids')
    return {'date': str(day), 'games': gm}


def slate_payload(schedule, board, f, status, sources, unmatched, odds_note, games, day):
    def tip(home, away):
        t = board.loc[board['TEAM_ID'].isin([home, away]), 'commence_time'].dropna()
        return t.iloc[0] if len(t) else None
    gm = game_rows(schedule, day, games, tip)
    for g in gm:
        g['props'] = int(board['TEAM_ID'].isin(g.pop('ids')).sum())
    skip = board['skip']
    return {'games': gm, 'n_props': int(len(board)), 'n_eligible': int((skip == '').sum()),
            'skipped': {'injury': int(skip.str.startswith('on injury').sum()), 'b2b': int((skip == 'back-to-back').sum())},
            'board': [row_payload(r) for _, r in board.head(15).iterrows()],
            'injuries': status[['name', 'status', 'source']].to_dict('records'),
            'slate': {'odds': odds_note, 'injury_info': pd.Series(sources).value_counts().to_dict(),
                      'unmatched_report_names': unmatched}}


# ---------------------------------------------------------------- log, close, results

def read_bets(path):
    log = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=LOG_COLS)
    log['market'] = log['market'].fillna('points') if 'market' in log else 'points'
    return log.astype({'result': object, 'close_line': float, 'close_novig_side': float, 'clv': float,
                       'points': float, 'units': float})


def read_log(paths):
    return read_bets(paths.log)


def uses_corrections(paths):
    return paths.log.parent == DATA and CORRECTED.exists()             # the real log only, never a replay


def log_bets(paths, day, bets):
    log = read_log(paths)
    log = log[log['date'].astype(str) != day]                  # a rerun replaces that day's bets
    new = pd.DataFrame(bets).reindex(columns=LOG_COLS)
    log = new if log.empty else pd.concat([log, new], ignore_index=True) if len(new) else log
    log.to_csv(paths.log, index=False)


def run_close(paths, window_min):
    """Closing snapshots for today's bets: one per game, once that game is within `window_min` of tip."""
    if not CLOSE_LINES:
        return 'closing lines are off (config.CLOSE_LINES)'
    log = read_log(paths)
    today = str(dt.datetime.now(ET).date())
    todo = log[(log['date'].astype(str) == today) & log['close_line'].isna()]
    if todo.empty:
        return 'no open bet needing a close line'
    now = pd.Timestamp.now(tz='UTC')
    tips = todo.groupby('event_id')['commence_time'].first().map(pd.Timestamp)
    due = tips[(tips > now) & (tips <= now + pd.Timedelta(minutes=window_min))]
    if due.empty:
        return 'not yet: next tip ' + f"{tips[tips > now].min().tz_convert(ET):%I:%M %p} ET" if (tips > now).any() else 'no game left to close'
    from daily_logger import snapshot
    from odds_api import OddsAPI
    api = OddsAPI()
    snapshot(api, [{'id': e, 'commence_time': t.strftime('%Y-%m-%dT%H:%M:%SZ')} for e, t in due.items()], 'close')
    parse_live()
    done = []
    for i, b in todo[todo['event_id'].isin(due.index)].iterrows():
        sfx = '' if b['market'] == 'points' else f"_{b['market']}"
        path = DATA / 'live' / f'odds_lines{sfx}.parquet'
        if not path.exists():
            done.append(f"{b['player']} {b['market']}: no close file"); continue
        lines = pd.read_parquet(path)
        row = lines[(lines['event_id'] == b['event_id']) & (lines['player'].map(norm) == norm(b['player']))]
        if row.empty or pd.isna(row['close_line'].iloc[0]):
            done.append(f"{b['player']}: no longer listed")
            continue
        r, over = row.iloc[0], b['side'] == 'OVER'
        log.loc[i, 'close_line'] = r['close_line']
        log.loc[i, 'close_novig_side'] = r['close_novig_over'] if over else 1 - r['close_novig_over']
        log.loc[i, 'clv'] = (r['close_line'] - b['line']) * (1 if over else -1)    # points the line moved our way
        done.append(f"{b['player']} close {r['close_line']} ({log.loc[i, 'clv']:+.1f})")
    log.to_csv(paths.log, index=False)
    return 'close line ' + '; '.join(done)


@functools.cache
def stat_box():
    """{(GAME_ID, PLAYER_ID): {'reb': .., 'ast': ..}} from the box score files."""
    import stat_backtest as SB
    b = SB.box_stats()
    return {(g, int(p)): {'reb': r, 'ast': a} for g, p, r, a in zip(b['GAME_ID'], b['PLAYER_ID'], b['reb'], b['ast'])}


def settle(paths, games):
    """Grade the posted bets, and the corrected picks the site shows in their place."""
    n = settle_file(paths.log, games)
    if uses_corrections(paths):
        settle_file(CORRECTED, games)
    return n


def settle_file(path, games):
    """Grade unsettled bets whose games are in the box scores (DNP = void)."""
    log = read_bets(path)
    if log.empty:
        return 0
    n = 0
    for i, b in log[log['result'].isna()].iterrows():
        g = games[(games['PLAYER_ID'] == b['PLAYER_ID']) & (games['GAME_DATE'] == pd.Timestamp(b['date']))]
        if g.empty:
            continue
        if not g['played'].iloc[0]:
            log.loc[i, ['result', 'units']] = ['void', 0.0]
        else:
            if b['market'] in STAT_MARKETS:
                v = stat_box().get((str(g['GAME_ID'].iloc[0]), int(b['PLAYER_ID'])))
                if v is None:
                    continue                                  # that box score has no rebounds/assists yet
                pts = v[STAT_MARKETS[b['market']]]
            else:
                pts = g['points'].iloc[0]
            won = pts > b['line'] if b['side'] == 'OVER' else pts < b['line']
            log.loc[i, 'points'] = pts
            log.loc[i, 'result'] = 'push' if pts == b['line'] else ('win' if won else 'loss')
            log.loc[i, 'units'] = 0.0 if pts == b['line'] else \
                b['stake'] * (float(american_to_decimal(b['price'])) - 1 if won else -1)
        n += 1
    log.to_csv(path, index=False)
    return n


def finals_for(games, site):
    """Final points for every prop on a day's board: {'ids': {PLAYER_ID: pts}, 'names': {name: pts}}, None = DNP.
    None if that day's box scores aren't in yet."""
    g = games[games['GAME_DATE'] == pd.Timestamp(site['date'])]
    if g.empty:
        return None
    pts = lambda r: float(r['points']) if r['played'] else None
    ids = {int(r['PLAYER_ID']): pts(r) for _, r in g.iterrows()}
    names = {r['player_name']: pts(r) for _, r in g.iterrows()}
    want_ids = {int(p['id']) for p in site.get('props') or []}
    want_names = {b['player'] for b in site.get('board') or []}
    out = {'ids': {str(i): v for i, v in ids.items() if i in want_ids},
           'names': {n: v for n, v in names.items() if n in want_names}}
    if site.get('markets'):                              # rebounds/assists boards: the stat itself
        box, out['markets'] = stat_box(), {}
        for market, key in STAT_MARKETS.items():
            want = {int(x['id']) for x in (site['markets'].get(market) or {}).get('props') or []}
            vals = {}
            for _, r in g[g['PLAYER_ID'].isin(want)].iterrows():
                v = box.get((r['GAME_ID'], int(r['PLAYER_ID'])), {}).get(key)
                if r['played'] and (v is None or pd.isna(v)):
                    continue                             # played, box score row not in yet
                vals[str(int(r['PLAYER_ID']))] = float(v) if r['played'] else None
            out['markets'][market] = vals
    return out


def add_finals(paths, games, site, days=3):
    """The edge board's results: final points on the current page and the last few days' saved pages."""
    n = 0
    if f := finals_for(games, site):                    # recomputed each run: an early run may have caught games still on
        site['finals'] = f; n += 1
    hist = paths.site / 'history'
    for path in sorted(hist.glob('20*.json'))[-days:]:
        if path.stem == site['date']:
            continue                                     # written by write_site from `site`
        day = json.loads(path.read_text())
        if f := finals_for(games, day):
            day['finals'] = f
            path.write_text(json.dumps(day, default=str)); n += 1
    return n


def run_results():
    season = season_of(dt.datetime.now(ET).date() - dt.timedelta(days=1))
    # ESPN, not stats.nba.com: the NBA's sites refuse cloud servers (GitHub Actions)
    for script, args in [('pull_box_scores_espn.py', []), ('build_features.py', [])]:
        r = subprocess.run([sys.executable, str(ROOT / script), *args], capture_output=True, text=True)
        if r.stderr.strip():
            print(r.stderr.strip()[-1500:])         # warnings (e.g. a skipped game) show in the run log
        if r.returncode != 0:
            raise RuntimeError(f'{script} failed: ' + ' '.join((r.stderr or r.stdout).split())[-400:])
    return pd.read_parquet(DATA / 'player_games.parquet')


def record(paths):
    """Season ledgers for the website. 'ledger': every bet as posted, settled or pending (X's records use this one).
    'site_ledger', when there are corrected picks: the same, with those dates' stat-market bets replaced by the picks
    re-made after a model fix, each flagged 'corrected'; the site's season history and home bars use it."""
    log = read_log(paths)
    if log.empty:
        return {'ledger': []}
    cols = ['date', 'player', 'team', 'opponent', 'market', 'side', 'line', 'price', 'book', 'edge', 'stake', 'result', 'won',
            'points', 'units', 'close_line', 'clv']
    rows = lambda x: json.loads(x.sort_values('date', kind='stable').assign(won=lambda y: y['result'].map({'win': True, 'loss': False}))[cols]
                                .rename(columns={'opponent': 'opp', 'close_line': 'close'}).to_json(orient='records'))
    out = {'ledger': rows(log)}
    if uses_corrections(paths):
        fix = read_bets(CORRECTED)
        keep = log[~(log['date'].astype(str).isin(set(fix['date'].astype(str))) & log['market'].isin(STAT_MARKETS))]
        site = rows(pd.concat([keep.assign(corrected=False), fix.assign(corrected=True)], ignore_index=True).astype({'corrected': bool}))
        flagged = fix.assign(key=fix['date'].astype(str) + fix['player'] + fix['market'] + fix['side'])
        keys = set(flagged['key'])
        for b in site:
            b['corrected'] = (str(b['date']) + b['player'] + b['market'] + b['side']) in keys
        out['site_ledger'] = site
        # X: the posted bets, except X_ADDED_DATES, where the corrected picks (posted bets plus any added) are reported
        dated = log['date'].astype(str).isin(X_ADDED_DATES) & log['market'].isin(STAT_MARKETS)
        was_posted = set(zip(log['date'].astype(str), log['player'], log['market'], log['side']))
        x = rows(pd.concat([log[~dated], fix[fix['date'].astype(str).isin(X_ADDED_DATES)]], ignore_index=True))
        for b in x:
            b['added'] = (str(b['date']), b['player'], b['market'], b['side']) not in was_posted
        out['x_ledger'] = x
    return out


def write_site(paths, site):
    site['record'] = record(paths)
    hist = paths.site / 'history'
    hist.mkdir(exist_ok=True)
    # 'tonight' (the next day's games, added by the morning results run) belongs to the front page only
    (hist / f"{site['date']}.json").write_text(json.dumps({k: v for k, v in site.items() if k != 'tonight'}, default=str))
    latest = max(p.stem for p in hist.glob('20*.json'))
    if site['date'] >= latest:                     # a replay of an older day never replaces the front page
        (paths.site / 'picks.json').write_text(json.dumps(site, indent=1, default=str))
    (hist / 'index.json').write_text(json.dumps(sorted(p.stem for p in hist.glob('20*.json'))))
    copy_pages(paths)


def copy_pages(paths):
    """The site's pages, past seasons (build_history*.py), shared styles and sportsbook logos into the published folder.
    rebounds.html and assists.html are both made from site/market.html."""
    src = ROOT / 'site'
    for page in [*src.glob('*.html'), *src.glob('seasons*.json'), src / 'model.js', src / 'common.css']:
        if page.name != 'market.html' and page.exists():
            shutil.copy(page, paths.site / page.name)
    tmpl = (src / 'market.html').read_text()
    for market in STAT_MARKETS:
        (paths.site / f'{market}.html').write_text(tmpl.replace('__MARKET__', market).replace('__TITLE__', market.capitalize()))
    shutil.copytree(src / 'img', paths.site / 'img', dirs_exist_ok=True)


def deploy(paths):
    """Upload data/site to Cloudflare (static assets; config in wrangler.jsonc, login from `npx wrangler login`)."""
    r = subprocess.run(['npx', '--yes', 'wrangler@4', 'deploy'], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError('Cloudflare upload failed: ' + (r.stderr or r.stdout)[-400:])
    return 'published'


def notify(msg):
    """Mac desktop notification when run locally; a no-op in the cloud run (no osascript on Linux)."""
    if shutil.which('osascript'):
        subprocess.run(['osascript', '-e', f'display notification "{msg[:200]}" with title "The Noon Line"'],
                       capture_output=True)


def clear_error(site):
    """A later run that succeeds takes down an earlier run's failure banner (the picks themselves are unchanged)."""
    if site.get('status') == 'error':
        site['status'], site['message'] = 'ok', ''
    return site


def error_banner(paths, mode, err):
    path = paths.site / 'picks.json'
    site = json.loads(path.read_text()) if path.exists() else {'date': str(dt.datetime.now(ET).date())}
    site['status'] = 'error'
    site['message'] = f'The {mode} update failed at {dt.datetime.now(ET):%I:%M %p} ET: {err}'
    path.write_text(json.dumps(site, indent=1, default=str))
    copy_pages(paths)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['picks', 'close', 'results', 'remove'])
    ap.add_argument('--replay', action='store_true', help='use stored data only (no API calls)')
    ap.add_argument('--date', help='picks: day to run (default today, ET)')
    ap.add_argument('--start')
    ap.add_argument('--end')
    ap.add_argument('--window', type=int, default=10, help='close: minutes before tip')
    ap.add_argument('--no-deploy', action='store_true', help="don't upload to Cloudflare")
    ap.add_argument('--set', default=os.environ.get('OVERRIDE', ''),
                    help='picks: "Player=Status, ..." (Available/Probable/Questionable/Doubtful/Out), saved for the day')
    ap.add_argument('--if-missing', action='store_true', help="picks: do nothing if today's picks already ran")
    ap.add_argument('--refresh-lines', action='store_true',
                    help="picks rerun: take new lines for games not yet started (the noon ones move to odds_live/noon/)")
    ap.add_argument('--late-report', action='store_true',
                    help="picks: today's ran without an injury report; redo it with the newest one (the Worker starts this)")
    args = ap.parse_args()
    paths = Paths(args.replay)
    stamp = dt.datetime.now(ET)
    try:
        if args.mode == 'picks':
            if args.start:
                days = pd.date_range(args.start, args.end).date
            else:
                days = [dt.date.fromisoformat(args.date) if args.date else stamp.date()]
            prev = json.loads((paths.site / 'picks.json').read_text()) if (paths.site / 'picks.json').exists() else {}
            if args.if_missing and prev.get('date') == str(days[0]) and prev.get('status') == 'ok':
                print(f'{days[0]}: picks already ran at {prev.get("updated")}; backup run does nothing')
                return
            if args.late_report and (prev.get('slate') or {}).get('report') not in ('missing', 'early', 'none'):
                print(f'{days[0]}: picks already used an injury report; nothing to redo')
                return
            extra = parse_overrides(args.set)            # checked before anything runs
            games = pd.read_parquet(DATA / 'player_games.parquet') if args.replay else None
            for day in days:
                now = dt.datetime(day.year, day.month, day.day, 12, 10, tzinfo=ET) if args.replay else stamp
                site = run_picks(day, paths, args.replay, now, extra, args.late_report, args.refresh_lines)
                if extra and not args.replay:
                    save_overrides(day, site['slate']['overrides'])
                if args.replay:
                    settle(paths, games)            # replays know the result already
                write_site(paths, site)
                print(f"{day}: " + ('; '.join(f"BET {p['player']} {p['side']} {p['line']} {p.get('market', 'points')} @ {p['price']:+d} {p['book']} "
                                              f"(edge {p['edge']:+.1%}, {p['stake']:g}u)" for p in site['picks'])
                                    or site['message']), flush=True)
            if not args.replay and site['picks']:
                notify(f"{len(site['picks'])} bet(s): " + ', '.join(f"{p['player']} {p['side'].lower()} {p['line']}"
                                                                   for p in site['picks']))
        elif args.mode == 'remove':
            print(remove_bets(paths, args.set))
        elif args.mode == 'close':
            msg = run_close(paths, args.window)
            print(msg)
            if not msg.startswith('close line'):
                return                              # nothing new: no rewrite, no upload
            site = clear_error(json.loads((paths.site / 'picks.json').read_text()))
            write_site(paths, site)
        else:
            games = run_results()
            n = settle(paths, games)
            path = paths.site / 'picks.json'
            site = clear_error(json.loads(path.read_text())) if path.exists() else {'date': str(stamp.date())}
            k = add_finals(paths, games, site)
            if not args.replay and site.get('date') != str(stamp.date()):
                try:                                     # tonight's games until the noon run; never fails the results
                    site['tonight'] = tonight_payload(games, stamp.date())
                except Exception as e:
                    print(f'tonight: skipped ({type(e).__name__}: {e})')
            write_site(paths, site)
            print(f'settled {n} bet(s); final points on {k} day(s) of edge boards')
        if not args.replay and not args.no_deploy:
            print(deploy(paths))
            if args.mode in ('picks', 'results'):        # once each per day, after the site is live; never fails the run
                from post_x import post_picks, post_results
                if args.mode == 'picks' and site.get('slate', {}).get('report') in ('missing', 'early'):
                    print('X: waiting for the injury report (the rerun posts)')
                else:
                    print(post_picks(site) if args.mode == 'picks' else post_results(site))
    except OverrideError as e:                   # a typo in an override: say so, leave the site as it was
        print(f'ERROR: {e}')
        sys.exit(1)
    except Exception as e:
        traceback.print_exc()
        error_banner(paths, args.mode, f'{type(e).__name__}: {e}')
        if not args.replay and not args.no_deploy and 'Cloudflare' not in str(e):
            try:
                deploy(paths)                       # put the failure banner on the live site
            except Exception:
                pass
        notify(f'{args.mode} update failed: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
