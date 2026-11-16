"""Post to X: the day's bets after the noon picks run, last night's results after the 9 AM results run.

daily_pipeline.py calls post_picks (picks mode) and post_results (results mode) once the site is published.
Credentials (GitHub secrets), either kind; without them nothing is posted:
  OAuth 2.0 (what X's developer console issues now): X_CLIENT_ID, X_CLIENT_SECRET, X_REFRESH_TOKEN (the refresh token
    from "Generate" on the app's Access Token, Read and write) and X_TOKEN_KEY (any long random string). X access
    tokens last 2 hours and every refresh token works once, so each post refreshes and keeps the new refresh token
    encrypted with X_TOKEN_KEY in data/live/x_token.enc (committed by the run like the rest of data/live). Setting a
    new X_REFRESH_TOKEN secret (re-authorising) takes precedence over the saved one.
  OAuth 1.0a: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET.
Noon: one post per model with bets, each bet as player, side, line and sportsbook (nothing else); a model with no
bets isn't posted, and a day with no bets at all gets one short "No bets today" post. 9 AM: one model update with each
model's units last night and on the season, and all models together (the site's ledger, so the two agree); on Mondays
also the weekly scorecard. Each post goes out once (data/live/x_posted.json); nothing on days without games; the
update only once the night's bets are all settled; text only, no site link (the site is private, and a link costs more per post).

    python post_x.py --dry-run       # print what today's posts would say
    ANNOUNCE='text' python post_x.py --announce     # one-off post (the workflow's 'announce' mode)
    ANNOUNCE='picks' python post_x.py --announce    # repost today's picks after a rerun changed them ("Updated")
    python post_x.py --connect       # on your computer: approve posting (text and images) in X, saves X_REFRESH_TOKEN
    python post_x.py --check         # sign in and report the account and permissions, post nothing (workflow 'xcheck')
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import DATA

URL = 'https://api.x.com/2/tweets'
POSTED = DATA / 'live' / 'x_posted.json'
KEYS = ['X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_SECRET']                # OAuth 1.0a
OAUTH2 = ['X_CLIENT_ID', 'X_CLIENT_SECRET', 'X_REFRESH_TOKEN', 'X_TOKEN_KEY']            # OAuth 2.0
TOKEN_URL = 'https://api.x.com/2/oauth2/token'
TOKEN_FILE = DATA / 'live' / 'x_token.enc'
SCOPES = None                                               # the OAuth 2.0 token's scopes, for error messages
LIMIT = 280
SETTLED = ('win', 'loss', 'push', 'void')

side = lambda b: 'O' if b['side'] == 'OVER' else 'U'
STAT = {'points': 'pts', 'rebounds': 'reb', 'assists': 'ast'}
stat = lambda b: STAT.get(b.get('market') or 'points', 'pts')        # bets before markets existed are points
units = lambda v: (lambda r: f"{'+' if r >= 0 else '-'}{abs(r):.1f}u")(round(v, 1) + 0.0)        # rounded first: no '-0.0u'
day_label = lambda d: f"{date.fromisoformat(d):%a %b} {date.fromisoformat(d).day}"


def record(bets, pct=True):
    """'14-12 · +1.8u (+5.2%)' over settled bets (pushes and voids count toward units, not the record)."""
    s = [b for b in bets if b.get('result') in SETTLED]
    w, l = sum(b['result'] == 'win' for b in s), sum(b['result'] == 'loss' for b in s)
    u = sum(b['units'] or 0 for b in s)
    risked = sum(b['stake'] for b in s if b['result'] in ('win', 'loss', 'push'))
    return f"{w}-{l} · {units(u)}" + (f" ({u / risked:+.1%})" if pct and risked else '')


BOOK = {'DraftKings': 'DK', 'FanDuel': 'FD', 'BetMGM': 'MGM', 'Caesars': 'CZR'}
TAGS_PICKS = '#NBA #NBAPicks #PlayerProps'                  # two or three tags, on the first post of a thread only
TAGS_RESULTS = '#NBA #NBABets'


def pick_line(p):
    """'Kobe Sanders U 12.5 pts · -108 DK' (and the stake when it isn't 1u)."""
    size = f" · {p['stake']:g}u" if p.get('stake', 1) != 1 else ''
    return f"{p['player']} {side(p)} {p['line']:g} {stat(p)} · {p['price']:+d} {BOOK.get(p['book'], p['book'])}{size}"


MODELS = [('points', 'Points'), ('rebounds', 'Rebounds'), ('assists', 'Assists')]
market_of = lambda b: b.get('market') or 'points'
ledger_of = lambda site: (site.get('record') or {}).get('x_ledger') or (site.get('record') or {}).get('ledger', [])   # what X reports
site_ledger_of = lambda site: (site.get('record') or {}).get('site_ledger') or (site.get('record') or {}).get('ledger', [])   # the site's season records
def picks_posts(site, market, note=''):
    """One model's bets today, best edge first, one line each; [] without bets. Bets that don't fit continue in replies."""
    bets = sorted([p for p in site.get('picks') or [] if market_of(p) == market], key=lambda p: -p['edge'])
    if not bets:
        return []
    head = f"The Noon Line · {dict(MODELS)[market]} · {day_label(site['date'])}{note}"
    posts, cur = [], [head, '']
    for line in map(pick_line, bets):
        tail = ['', TAGS_PICKS] if not posts else []
        if len('\n'.join(cur + [line] + tail)) > LIMIT and len(cur) > (2 if not posts else 0):
            posts.append('\n'.join(cur + tail)); cur = []
        cur.append(line)
    posts.append('\n'.join(cur + (['', TAGS_PICKS] if not posts else [])))
    return posts


def picks_text(site):
    return '\n\n=====\n\n'.join('\n\n---\n\n'.join(picks_posts(site, m)) or f'({m}: no bets, no post)' for m, _ in MODELS)     # for --dry-run


def night(site, market=None):
    """The page day's bets (one model's, or all) from the ledger, or [] if none or any is still unsettled."""
    bets = [b for b in ledger_of(site) if b['date'] == site['date'] and (market is None or market_of(b) == market)
            and not (b.get('added') and b.get('result') not in SETTLED)]       # an added bet that can't be graded never holds up a post
    return bets if bets and all(b.get('result') in SETTLED for b in bets) else []


def week_text(ledger, monday):
    """The Monday scorecard for the 7 days before `monday`: record and units, season, line movement."""
    start = (date.fromisoformat(monday) - timedelta(days=7)).isoformat()
    week = [b for b in ledger if start <= b['date'] < monday and b.get('result') in SETTLED]
    season = [b for b in ledger if b['date'] < monday]
    s, e = date.fromisoformat(start), date.fromisoformat(monday) - timedelta(days=1)
    span = f"{s:%b} {s.day}-{e.day}" if s.month == e.month else f"{s:%b} {s.day}-{e:%b} {e.day}"
    lines = [f"Week of {span}: {record(week)}", f"Season: {record(season)}"]
    moved = [b for b in season if b.get('clv') is not None and b['clv'] != 0]
    if moved:
        ours = sum(b['clv'] > 0 for b in moved)
        lines.append(f"Line moved our way after the pick: {ours} of {len(moved)} ({ours / len(moved):.0%})")
    best = max(week, key=lambda b: b['units'] or 0)
    if (best['units'] or 0) > 0:
        lines.append(f"Best hit: {best['player']} {side(best)} {best['line']:g} {stat(best)} ({best['points']:g})")
    return '\n'.join(['The Noon Line · weekly scorecard', ''] + lines + ['', 'Every bet counted, wins and losses.', TAGS_RESULTS])[:LIMIT]


def update_text(site):
    """The 9 AM model update: each model's units last night (or 'no bets') and on the season, then all models."""
    led = [b for b in site_ledger_of(site) if b['date'] <= site['date'] and b.get('result') in SETTLED]
    u = lambda bets: units(sum(b['units'] or 0 for b in bets))
    lines = []
    for m, name in MODELS + [(None, 'All models')]:
        mine = [b for b in led if m is None or market_of(b) == m]
        last = [b for b in mine if b['date'] == site['date']]
        if mine:
            lines.append(f"{name}: {u(last) + ' last night' if last else 'no bets'} · {u(mine)} season")
    return '\n'.join([f"The Noon Line · Model update · {day_label(site['date'])}", '', *lines, '', TAGS_RESULTS])


def post_once(key, text, image=None):
    """Post `text` (or a list of posts, as a thread) unless `key` was already posted; `image` (PNG bytes, or a list of
    them, up to 4) goes on the first post when it uploads. Returns a one-line status; never raises (posting must not fail
    a run)."""
    try:
        if not (all(os.environ.get(k) for k in OAUTH2) or all(os.environ.get(k) for k in KEYS)):
            return 'X: keys not set, nothing posted'
        done = json.loads(POSTED.read_text()) if POSTED.exists() else {}
        if key in done:
            return f'X: already posted {key}'
        import requests
        auth, first, prev = auth_header(), None, None
        images = [i for i in (image if isinstance(image, list) else [image]) if i][:4]
        media = [m for m in (upload_image(i, auth) for i in images) if m] if images and auth.startswith('Bearer') else []
        for t in ([text] if isinstance(text, str) else text):
            body = {'text': t, **({'reply': {'in_reply_to_tweet_id': prev}} if prev else {}),
                    **({'media': {'media_ids': media}} if media and not prev else {})}
            r = requests.post(URL, json=body, timeout=30, headers={'Authorization': auth})
            if r.status_code != 201:
                scope = f' [token scopes: {SCOPES}]' if SCOPES is not None else ''
                if first:                                # part of the thread is up: record it so it isn't reposted
                    done[key] = first
                    POSTED.write_text(json.dumps(done, indent=1))
                return f"X: post failed ({r.status_code}): {' '.join(r.text.split())[:300]}{scope}"
            prev = r.json()['data']['id']
            first = first or prev
        done[key] = first
        POSTED.parent.mkdir(exist_ok=True)
        POSTED.write_text(json.dumps(done, indent=1))
        return f"X: posted {key} ({done[key]}){f' with {len(media)} image' + ('s' if len(media) > 1 else '') if media else ''}"
    except Exception as e:
        return f'X: post failed ({type(e).__name__}: {e})'


def posted_keys():
    return json.loads(POSTED.read_text()) if POSTED.exists() else {}


def post_picks(site):
    """Noon: one post per model with bets, or one 'No bets today' post (nothing on days without games or a failed run)."""
    if not site.get('games') or site.get('status') == 'error':
        return 'X: no games or no picks today, nothing posted'
    if site['date'] in posted_keys():                   # posted before the per-model format: don't repost the day
        return f"X: already posted {site['date']}"
    out = [post_once(f"{site['date']}:{m}", picks_posts(site, m)) for m, _ in MODELS if picks_posts(site, m)]
    return '; '.join(out) or post_once(f"{site['date']}:none", f"The Noon Line · {day_label(site['date'])}\n\nNo bets today.")


def post_results(site, today=None):
    """9 AM: the model update for last night (once its bets are all settled); on Mondays also the weekly scorecard."""
    done = posted_keys()
    if 'results:' + site['date'] in done or any(f"results:{site['date']}:{m}" in done for m, _ in MODELS):
        out = [f"X: already posted results for {site['date']}"]            # the old per-model results format
    elif night(site):
        out = [post_once('update:' + site['date'], update_text(site))]
    else:
        out = ['X: no settled bets for that night, nothing posted']
    today = today or datetime.now(ZoneInfo('America/New_York')).date()
    if today.weekday() == 0:
        monday, ledger = today.isoformat(), site_ledger_of(site)
        start = (today - timedelta(days=7)).isoformat()
        if any(start <= b['date'] < monday and b.get('result') in SETTLED for b in ledger):
            out.append(post_once('week:' + monday, week_text(ledger, monday)))
    return '; '.join(out)


if __name__ == '__main__':
    site = json.loads((DATA / 'site' / 'picks.json').read_text())
    if '--connect' in sys.argv:                           # on your own computer: authorize and store the token
        connect()
    elif '--check' in sys.argv:                             # workflow 'xcheck' mode: sign in like a post would, post nothing
        import requests
        auth = auth_header()
        if not auth:
            print('X check: keys not set'); sys.exit(1)
        me = requests.get('https://api.x.com/2/users/me', headers={'Authorization': auth}, timeout=30)
        user = me.json().get('data', {}).get('username') if me.status_code == 200 else f'error {me.status_code}: {me.text[:150]}'
        print(f'X check: signed in as @{user}; token scopes: {SCOPES}')
        print('X check: images', 'ENABLED (media.write)' if SCOPES and 'media.write' in SCOPES else 'NOT enabled: posts go out as text')
    elif '--authorize' in sys.argv:                         # workflow 'xauth' mode: $ANNOUNCE = "<code> <verifier>"
        code, verifier = os.environ.get('ANNOUNCE', '').split()
        print('X: authorized, token scopes:', authorize(code, verifier))
    elif '--announce' in sys.argv:                          # one-off post (workflow 'announce' mode), text from $ANNOUNCE
        text = os.environ.get('ANNOUNCE', '').strip()
        if text.lower() == 'picks':                       # the day's picks changed after the noon post
            for m, _ in MODELS:                            # one update per model, each distinct version posted once
                posts = picks_posts(site, m, ' · Updated')
                if posts:
                    print(post_once(f"{site['date']}:{m}:update:" + hashlib.sha256('|'.join(posts).encode()).hexdigest()[:12], posts))
            sys.exit()
        print(post_once('announce:' + hashlib.sha256(text.encode()).hexdigest()[:12], text) if text else 'X: no text given')
    elif '--dry-run' in sys.argv:
        print(picks_text(site), '\n=====')
        print(update_text(site) if night(site) else 'update: nothing settled for that night', '\n---')
        print(week_text(site_ledger_of(site), sys.argv[-1] if sys.argv[-1][:2] == '20' else date.today().isoformat()))
    else:
        print(post_picks(site))
