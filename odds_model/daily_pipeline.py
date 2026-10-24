"""The daily run: noon pick, closing line, next-morning settle. Writes the website's data file.

    python daily_pipeline.py picks       # ~12:15 ET: noon odds + injury report -> the day's bets (or none)
    python daily_pipeline.py close       # every ~15 min in the evening: closing lines for games with a bet
    python daily_pipeline.py results     # next morning: box scores -> features -> settle the bets

    python daily_pipeline.py picks --replay --date 2026-03-19     # replay a past day from stored data
    python daily_pipeline.py picks --replay --start 2026-03-01 --end 2026-03-31

The bets follow the backtested rule exactly:
  absences   noon injury report: Out/Doubtful count fully, Questionable half; teams that have not filed
             (noon, then previous evening) fall back to whoever missed their previous game
  skip       players on the report (Probable/Questionable/Doubtful) and players on a back-to-back
  bet        every remaining prop with an edge >= 2%, at the best price among config.BOOKS
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

from config import BOOKS, DATA, LIVE, ROOT, SPORT
from injury_reports import flip_name
from name_map import norm, roster_match
from parse_odds import american_to_decimal, american_to_prob
from predict_today import ET, likely_out, load_schedule, predict_day, season_of

ON_REPORT = {'Probable', 'Questionable', 'Doubtful'}
WEIGHT = {'Out': 1.0, 'Doubtful': 1.0, 'Questionable': 0.5}
MIN_EDGE = 0.02
STAKE = 1.0
REPORT_DIR = DATA / 'injury_reports'
LOG_COLS = ['date', 'player', 'PLAYER_ID', 'team', 'opponent', 'event_id', 'commence_time', 'side', 'line', 'price',
            'book', 'p_side', 'edge', 'stake', 'close_line', 'close_novig_side', 'clv', 'points', 'result', 'units']


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


def noon_report(day, now, allow_fetch):
    """The most recent report at or before noon ET (falls back to earlier same-day reports)."""
    path = REPORT_DIR / f'{day}_noon.csv'
    if path.exists() or not allow_fetch:
        return fetch_report(None, path, False)
    noon = dt.datetime(day.year, day.month, day.day, 12, 0)
    latest = min(noon, now.replace(tzinfo=None))
    for back in range(0, 4 * 60 + 1, 15):              # newest first, every 15 min back 4 hours
        ts = latest - dt.timedelta(minutes=back)
        ts = ts.replace(minute=ts.minute - ts.minute % 15, second=0, microsecond=0)
        rep = fetch_report(ts, path, True)
        if rep is not None:
            return rep
    return None


def tidy(rep, day):
    rep = rep[pd.to_datetime(rep['Game Date'], format='%m/%d/%Y', errors='coerce') == pd.Timestamp(day)].copy()
    rep['Team'] = rep['Team'].ffill()
    rep['not_submitted'] = rep['Reason'].astype(str).str.contains('NOT YET SUBMITTED')
    return rep


def injury_weights(games, day, schedule, now, allow_fetch):
    """{PLAYER_ID: weight}, per-player status table, and where each team's info came from."""
    season = season_of(day)
    cur = games[(games['season'] == season) & (games['GAME_DATE'] < pd.Timestamp(day))]
    nick = cur.drop_duplicates('TEAM_ID').set_index('teamName')['TEAM_ID']
    team_id = lambda t: next((nick[n] for n in nick.index if str(t).endswith(n)), None)
    roster = cur.drop_duplicates(['TEAM_ID', 'PLAYER_ID'])[['TEAM_ID', 'PLAYER_ID', 'player_name']].copy()
    roster['key'] = roster['player_name'].map(norm)
    teams = set(schedule['TEAM_ID'])

    sources, rows = {}, []
    noon = noon_report(day, now, allow_fetch)
    reports = [('noon report', tidy(noon, day))] if noon is not None else []
    if noon is not None and reports[0][1]['not_submitted'].any():
        prev = day - dt.timedelta(days=1)
        path = REPORT_DIR / f'{day}_prevday.csv'
        for hour in (22, 20, 17):
            r = fetch_report(dt.datetime(prev.year, prev.month, prev.day, hour, 0), path, allow_fetch)
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
    return weights, status, sources, list(unmatched['name'])


# ---------------------------------------------------------------- odds

def pull_noon_odds():
    """Noon snapshot of every game tipping today (1 credit each), parsed to data/live/odds_lines.parquet."""
    from daily_logger import snapshot
    from odds_api import OddsAPI
    api = OddsAPI()
    now = dt.datetime.now(dt.timezone.utc)
    start = lambda e: dt.datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00'))
    events = [e for e in api.get(f'/sports/{SPORT}/events', expected_cost=0) or []
              if start(e).astimezone(ET).date() == now.astimezone(ET).date() and start(e) > now]
    saved = snapshot(api, events, 'early')
    parse_live()
    return f'{len(events)} games, {saved} new snapshots, credits left {api.remaining}'


def parse_live():
    (DATA / 'live').mkdir(exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / 'parse_odds.py'), '--raw-dir', str(LIVE),
                    '--out-dir', str(DATA / 'live')], check=True, capture_output=True)


# ---------------------------------------------------------------- the pick

def make_board(f, status):
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
    b['skip'] = np.select([b['status'].isin(ON_REPORT), b['rest_days'] == 1],
                          ['on injury report (' + b['status'].fillna('') + ')', 'back-to-back'], '')
    bet = (b['skip'] == '') & (b['edge'] >= MIN_EDGE)
    b['play'] = np.where(b['skip'] != '', 'skip: ' + b['skip'], np.where(bet, 'BET ' + b['side'] + f' {STAKE:g}u',
                                                                          'pass: edge < 2%'))
    b['stake'] = np.where(bet, STAKE, np.nan)
    b = b.sort_values('edge', ascending=False)
    return b, list(b.index[bet.reindex(b.index)])


def run_picks(day, paths, replay, now):
    games = pd.read_parquet(DATA / 'player_games.parquet')
    schedule = load_schedule(games, day, from_history=replay)
    site = {'date': str(day), 'updated': now.strftime('%Y-%m-%d %I:%M %p ET'), 'status': 'ok', 'message': '',
            'picks': [], 'board': [], 'injuries': [], 'games': [], 'slate': {}}
    if schedule.empty:
        site['message'] = 'No games today.'
        return site
    odds_note = 'replay: historical noon lines' if replay else pull_noon_odds()
    weights, status, sources, unmatched = injury_weights(games, day, schedule, now, allow_fetch=not replay)
    om = joblib.load(DATA / 'models' / 'over_model.pkl')
    try:
        f = predict_day(games, day, schedule, out_weights=weights)
    except ValueError as e:                     # first night of a season: nothing to project from yet
        site['message'] = str(e)
        return site
    if 'p_over' not in f:
        site['status'], site['message'] = 'error', 'No noon lines were found for today\'s games.'
        return site
    board, bet_idx = make_board(f, status)

    site.update(slate_payload(schedule, board, f, status, sources, unmatched, odds_note, games))
    site['props'] = props_payload(board)
    site['model'] = model_payload(om)
    site['roster'] = roster_payload(games, day, schedule, weights, status, export_model(paths))
    check_browser_model(paths, site, f)
    bets = []
    for i in bet_idx:
        p = board.loc[i]
        bet = {'date': str(day), 'player': p['player_name'], 'PLAYER_ID': int(p['PLAYER_ID']), 'team': abbr(p['team']),
               'opponent': abbr(team_names().get(p['OPP_ID'], '')), 'event_id': p.get('event_id'),
               'commence_time': p.get('commence_time'), 'side': p['side'], 'line': float(p['early_line']),
               'price': int(p['price']), 'book': BOOK_NAMES.get(p['book'], p['book']), 'p_side': round(float(p['p_side']), 4),
               'edge': round(float(p['edge']), 4), 'stake': float(p['stake'])}
        site['picks'].append({**bet, **row_payload(p), 'books': book_prices(p, replay),
                              'link': link(p.get('early_best_over_link' if p['side'] == 'OVER' else 'early_best_under_link'))})
        if replay and pd.notna(p.get('close_line')):        # replays know the close already
            over = p['side'] == 'OVER'
            bet['close_line'] = float(p['close_line'])
            bet['close_novig_side'] = float(p['close_novig_over'] if over else 1 - p['close_novig_over'])
            bet['clv'] = (bet['close_line'] - bet['line']) * (1 if over else -1)
        bets.append(bet)
    log_bets(paths, str(day), bets)
    if not bets:
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


BROWSER_COLS = ['pts_season', 'min_season', 'fga_season', 'team_fga_pg', 'out_fga_season_avg', 'out_fga_5']


def export_model(paths):
    """The minutes and points models as compact trees for site/model.js (written next to picks.json)."""
    pm = joblib.load(DATA / 'models' / 'points_model.pkl')

    def trees(model):
        d = model.booster_.dump_model()
        def node(n):
            if 'leaf_value' in n:
                return n['leaf_value']
            return [n['split_feature'], n['threshold'], int(n['default_left']), int(n['missing_type'] == 'NaN'),
                    node(n['left_child']), node(n['right_child'])]
        return {'features': d['feature_names'], 'trees': [node(t['tree_structure']) for t in d['tree_info']]}

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


def book_prices(p, replay):
    """Every book's noon price for the pick's side, scored against the same model probability."""
    path = DATA / ('odds_books.parquet' if replay else 'live/odds_books.parquet')
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


def slate_payload(schedule, board, f, status, sources, unmatched, odds_note, games):
    gm = []
    for gid, g in schedule.groupby('GAME_ID'):
        h, a = g.loc[g['is_home'] == 1, 'TEAM_ID'], g.loc[g['is_home'] == 0, 'TEAM_ID']
        if h.empty or a.empty:
            continue
        home, away = h.iloc[0], a.iloc[0]
        props = board[board['TEAM_ID'].isin([home, away])]
        tip = props['commence_time'].dropna()
        t = pd.Timestamp(tip.iloc[0]).tz_convert(ET) if len(tip) else None
        gm.append({'home': abbr(team_names().get(home, '')), 'away': abbr(team_names().get(away, '')),
                   'tip': t.strftime('%-I:%M %p ET') if t is not None else '', 't': t.isoformat() if t is not None else '',
                   'props': int(len(props))})
    gm.sort(key=lambda x: x['t'])
    skip = board['skip']
    return {'games': gm, 'n_props': int(len(board)), 'n_eligible': int((skip == '').sum()),
            'skipped': {'injury': int(skip.str.startswith('on injury').sum()), 'b2b': int((skip == 'back-to-back').sum())},
            'board': [row_payload(r) for _, r in board.head(15).iterrows()],
            'injuries': status[['name', 'status', 'source']].to_dict('records'),
            'slate': {'odds': odds_note, 'injury_info': pd.Series(sources).value_counts().to_dict(),
                      'unmatched_report_names': unmatched}}


# ---------------------------------------------------------------- log, close, results

def read_log(paths):
    log = pd.read_csv(paths.log) if paths.log.exists() else pd.DataFrame(columns=LOG_COLS)
    return log.astype({'result': object, 'close_line': float, 'close_novig_side': float, 'clv': float,
                       'points': float, 'units': float})


def log_bets(paths, day, bets):
    log = read_log(paths)
    log = log[log['date'].astype(str) != day]                  # a rerun replaces that day's bets
    new = pd.DataFrame(bets).reindex(columns=LOG_COLS)
    log = new if log.empty else pd.concat([log, new], ignore_index=True) if len(new) else log
    log.to_csv(paths.log, index=False)


def run_close(paths, window_min):
    """Closing snapshots for today's bets: one per game, once that game is within `window_min` of tip."""
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
    lines = pd.read_parquet(DATA / 'live' / 'odds_lines.parquet')
    done = []
    for i, b in todo[todo['event_id'].isin(due.index)].iterrows():
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


def settle(paths, games):
    """Grade unsettled bets whose games are in the box scores (DNP = void)."""
    log = read_log(paths)
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
            pts = g['points'].iloc[0]
            won = pts > b['line'] if b['side'] == 'OVER' else pts < b['line']
            log.loc[i, 'points'] = pts
            log.loc[i, 'result'] = 'push' if pts == b['line'] else ('win' if won else 'loss')
            log.loc[i, 'units'] = 0.0 if pts == b['line'] else \
                b['stake'] * (float(american_to_decimal(b['price'])) - 1 if won else -1)
        n += 1
    log.to_csv(paths.log, index=False)
    return n


def run_results():
    season = season_of(dt.datetime.now(ET).date() - dt.timedelta(days=1))
    # ESPN, not stats.nba.com: the NBA's sites refuse cloud servers (GitHub Actions)
    for script, args in [('pull_box_scores_espn.py', []), ('build_features.py', [])]:
        subprocess.run([sys.executable, str(ROOT / script), *args], check=True, capture_output=True)
    return pd.read_parquet(DATA / 'player_games.parquet')


def record(paths):
    """Season ledger for the website: every bet in order, settled or pending."""
    log = read_log(paths)
    if log.empty:
        return {'ledger': []}
    led = log.sort_values('date').assign(won=lambda x: x['result'].map({'win': True, 'loss': False}))
    cols = ['date', 'player', 'team', 'opponent', 'side', 'line', 'price', 'book', 'edge', 'stake', 'result', 'won',
            'points', 'units', 'close_line', 'clv']
    return {'ledger': json.loads(led[cols].rename(columns={'opponent': 'opp', 'close_line': 'close'})
                                 .to_json(orient='records'))}


def write_site(paths, site):
    site['record'] = record(paths)
    hist = paths.site / 'history'
    hist.mkdir(exist_ok=True)
    (hist / f"{site['date']}.json").write_text(json.dumps(site, default=str))
    latest = max(p.stem for p in hist.glob('20*.json'))
    if site['date'] >= latest:                     # a replay of an older day never replaces the front page
        (paths.site / 'picks.json').write_text(json.dumps(site, indent=1, default=str))
    (hist / 'index.json').write_text(json.dumps(sorted(p.stem for p in hist.glob('20*.json'))))
    copy_pages(paths)


def copy_pages(paths):
    """The site's pages, past seasons (build_history.py) and sportsbook logos (from site/) into the published folder."""
    for page in [*(ROOT / 'site').glob('*.html'), ROOT / 'site' / 'model.js', ROOT / 'site' / 'seasons.json']:
        shutil.copy(page, paths.site / page.name)
    shutil.copytree(ROOT / 'site' / 'img', paths.site / 'img', dirs_exist_ok=True)


def deploy(paths):
    """Upload data/site to Cloudflare (static assets; config in wrangler.jsonc, login from `npx wrangler login`)."""
    r = subprocess.run(['npx', '--yes', 'wrangler@4', 'deploy'], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError('Cloudflare upload failed: ' + (r.stderr or r.stdout)[-400:])
    return 'published'


def notify(msg):
    """Mac desktop notification when run locally; a no-op in the cloud run (no osascript on Linux)."""
    if shutil.which('osascript'):
        subprocess.run(['osascript', '-e', f'display notification "{msg[:200]}" with title "Belch Bets"'],
                       capture_output=True)


def error_banner(paths, mode, err):
    path = paths.site / 'picks.json'
    site = json.loads(path.read_text()) if path.exists() else {'date': str(dt.datetime.now(ET).date())}
    site['status'] = 'error'
    site['message'] = f'The {mode} update failed at {dt.datetime.now(ET):%I:%M %p} ET: {err}'
    path.write_text(json.dumps(site, indent=1, default=str))
    copy_pages(paths)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['picks', 'close', 'results'])
    ap.add_argument('--replay', action='store_true', help='use stored data only (no API calls)')
    ap.add_argument('--date', help='picks: day to run (default today, ET)')
    ap.add_argument('--start')
    ap.add_argument('--end')
    ap.add_argument('--window', type=int, default=10, help='close: minutes before tip')
    ap.add_argument('--no-deploy', action='store_true', help="don't upload to Cloudflare")
    args = ap.parse_args()
    paths = Paths(args.replay)
    stamp = dt.datetime.now(ET)
    try:
        if args.mode == 'picks':
            if args.start:
                days = pd.date_range(args.start, args.end).date
            else:
                days = [dt.date.fromisoformat(args.date) if args.date else stamp.date()]
            games = pd.read_parquet(DATA / 'player_games.parquet') if args.replay else None
            for day in days:
                now = dt.datetime(day.year, day.month, day.day, 12, 10, tzinfo=ET) if args.replay else stamp
                site = run_picks(day, paths, args.replay, now)
                if args.replay:
                    settle(paths, games)            # replays know the result already
                write_site(paths, site)
                print(f"{day}: " + ('; '.join(f"BET {p['player']} {p['side']} {p['line']} @ {p['price']:+d} {p['book']} "
                                              f"(edge {p['edge']:+.1%}, {p['stake']:g}u)" for p in site['picks'])
                                    or site['message']), flush=True)
            if not args.replay and site['picks']:
                notify(f"{len(site['picks'])} bet(s): " + ', '.join(f"{p['player']} {p['side'].lower()} {p['line']}"
                                                                   for p in site['picks']))
        elif args.mode == 'close':
            msg = run_close(paths, args.window)
            print(msg)
            if not msg.startswith('close line'):
                return                              # nothing new: no rewrite, no upload
            site = json.loads((paths.site / 'picks.json').read_text())
            write_site(paths, site)
        else:
            n = settle(paths, run_results())
            path = paths.site / 'picks.json'
            site = json.loads(path.read_text()) if path.exists() else {'date': str(stamp.date())}
            write_site(paths, site)
            print(f'settled {n} bet(s)')
        if not args.replay and not args.no_deploy:
            print(deploy(paths))
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
