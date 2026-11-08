"""Post to X: the day's bets after the noon picks run, last night's results after the 9 AM results run.

daily_pipeline.py calls post_picks (picks mode) and post_results (results mode) once the site is published.
Credentials (GitHub secrets), either kind; without them nothing is posted:
  OAuth 2.0 (what X's developer console issues now): X_CLIENT_ID, X_CLIENT_SECRET, X_REFRESH_TOKEN (the refresh token
    from "Generate" on the app's Access Token, Read and write) and X_TOKEN_KEY (any long random string). X access
    tokens last 2 hours and every refresh token works once, so each post refreshes and keeps the new refresh token
    encrypted with X_TOKEN_KEY in data/live/x_token.enc (committed by the run like the rest of data/live). Setting a
    new X_REFRESH_TOKEN secret (re-authorising) takes precedence over the saved one.
  OAuth 1.0a: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET.
One post per model (points, rebounds, assists), each with that model's season record and the overall record; a model
with no bets gets a 'no bets today' post saying why. Every bet is reported, wins and losses. Each post goes out once
(data/live/x_posted.json); nothing on days without games; results (per model with bets) only once that model's night
is settled;
no site link (the site is private, and a link costs more per post).

    python post_x.py --dry-run       # print what today's posts would say
    ANNOUNCE='text' python post_x.py --announce     # one-off post (the workflow's 'announce' mode)
    ANNOUNCE='picks' python post_x.py --announce    # repost today's picks after a rerun changed them ("Updated")
    python post_x.py --connect       # on your computer: approve posting (text and images) in X, saves X_REFRESH_TOKEN
    python post_x.py --check         # sign in and report the account and permissions, post nothing (workflow 'xcheck')
Images (x_cards.py) need the token's media.write scope; without it, or if an upload fails, posts go out as text.
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
units = lambda v: f"{'+' if v >= 0 else '-'}{abs(v):.1f}u"
day_label = lambda d: f"{date.fromisoformat(d):%a %b} {date.fromisoformat(d).day}"


def record(bets, pct=True):
    """'14-12 · +1.8u (+5.2%)' over settled bets (pushes and voids count toward units, not the record)."""
    s = [b for b in bets if b.get('result') in SETTLED]
    w, l = sum(b['result'] == 'win' for b in s), sum(b['result'] == 'loss' for b in s)
    u = sum(b['units'] or 0 for b in s)
    risked = sum(b['stake'] for b in s if b['result'] in ('win', 'loss', 'push'))
    return f"{w}-{l} · {units(u)}" + (f" ({u / risked:+.1%})" if pct and risked else '')


def fit(head, lines, tail):
    """head, a blank line, as many lines as fit 280 characters ('+N more' for the rest), then tail."""
    for k in range(len(lines), 0, -1):
        more = [f'+{len(lines) - k} more'] if k < len(lines) else []
        text = '\n'.join([head, '', *lines[:k], *more, '', *tail])
        if len(text) <= LIMIT:
            return text
    return '\n'.join([head, '', *tail])[:LIMIT]


BOOK = {'DraftKings': 'DK', 'FanDuel': 'FD', 'BetMGM': 'MGM', 'Caesars': 'CZR'}
TAGS_PICKS = '#NBA #NBAPicks #PlayerProps'                  # two or three tags, on the first post of a thread only
TAGS_RESULTS = '#NBA #NBABets'


def pick_block(p):
    """'Kobe Sanders U 12.5 (-108 DK)' and the reason: projection, chance to hit, season average."""
    why = f"Model {p['proj']:.1f} {stat(p)} · {p['p']:.0%} to hit"
    if p.get('season') is not None:
        why += f" · avg {p['season']:.1f}"
    return f"{p['player']} {side(p)} {p['line']:g} {stat(p)} ({p['price']:+d} {BOOK.get(p['book'], p['book'])})\n{why}"


MODELS = [('points', 'Points'), ('rebounds', 'Rebounds'), ('assists', 'Assists')]
market_of = lambda b: b.get('market') or 'points'


def records_tail(site, market, before=True):
    """'Rebounds season 3-1 · +1.8u' and 'All models 12-12 · -0.5u' over settled bets (before the page day, or through it)."""
    led = [b for b in (site.get('record') or {}).get('ledger', []) if (b['date'] < site['date'] if before else b['date'] <= site['date'])]
    name = dict(MODELS)[market]
    mine = [b for b in led if market_of(b) == market]
    out = [f"{name} season {record(mine, pct=False)}" if any(b.get('result') in SETTLED for b in mine) else f"{name} season 0-0"]
    if any(b.get('result') in SETTLED for b in led):
        out.append(f"All models {record(led, pct=False)}")
    return out


def no_bets_reason(site, market):
    """Why a model has no bets today, in a few words."""
    if site.get('message', '').startswith('No bets: the site sits out'):
        return 'the site sits out the last two weeks of the season'
    board = site.get('board') if market == 'points' else ((site.get('markets') or {}).get(market) or {}).get('board')
    if not board:
        return f'no {market} lines posted for tonight\'s games'
    top = [r for r in board if r.get('play') != 'skip']
    return f"best eligible edge {max(r['edge'] for r in top):+.1%}, under the 2% minimum" if top else 'every prop skipped (injury report, back-to-back)'


def picks_posts(site, market, note=''):
    """One model's bets today, best edge first, each with its reason; that model's season record and the overall record.
    Bets that don't fit continue in replies (a thread). No bets: one post saying so, and why."""
    name = dict(MODELS)[market]
    bets = sorted([p for p in site.get('picks') or [] if market_of(p) == market], key=lambda p: -p['edge'])
    head = f"The Noon Line · {name} · {day_label(site['date'])}{note}"
    recs = records_tail(site, market)
    if not bets:
        return ['\n\n'.join([head, f"No {market} bets today: {no_bets_reason(site, market)}.", '\n'.join(recs + [TAGS_PICKS])])]
    stake = f"{bets[0]['stake']:g}u each" if len(bets) > 1 else f"{bets[0]['stake']:g}u"
    tail = '\n'.join([f"{stake} · {recs[0]}", *recs[1:], TAGS_PICKS])
    blocks, posts = [pick_block(p) for p in bets], []
    cur = [head]
    for blk in blocks:
        trial = '\n\n'.join(cur + [blk] + ([tail] if not posts else []))
        if len(trial) <= LIMIT or len(cur) == (1 if not posts else 0):
            cur.append(blk)
        else:
            posts.append('\n\n'.join(cur + ([tail] if not posts else [])))
            cur = [blk]                                  # this bet starts the next post
    posts.append('\n\n'.join(cur + ([tail] if not posts else [])))
    if len(posts) > 1:
        posts = [t + f"\n({i + 1}/{len(posts)})" if len(t) + 6 <= LIMIT else t for i, t in enumerate(posts)]
    return posts


def picks_image(site, market):
    """PNG for one model's picks post, or None (no bets, or the image can't be drawn)."""
    try:
        import x_cards
        bets = sorted([p for p in site.get('picks') or [] if market_of(p) == market], key=lambda p: -p['edge'])
        return x_cards.picks_card(market, day_label(site['date']), bets, records_tail(site, market))
    except Exception:
        return None


def results_image(site, market):
    """PNG for one model's results post, or None."""
    try:
        import x_cards
        return x_cards.results_card(market, day_label(site['date']), night(site, market), records_tail(site, market, before=False))
    except Exception:
        return None


def picks_text(site):
    return '\n\n=====\n\n'.join('\n\n---\n\n'.join(picks_posts(site, m)) for m, _ in MODELS)     # for --dry-run


def night(site, market=None):
    """The page day's bets (one model's, or all) from the ledger, or [] if none or any is still unsettled."""
    bets = [b for b in (site.get('record') or {}).get('ledger', []) if b['date'] == site['date']
            and (market is None or market_of(b) == market)]
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


def results_text(site, market):
    """One model's bets from the night with the stat and result, the night's total, that model's season and the overall."""
    word = {'win': 'W', 'loss': 'L', 'push': 'push', 'void': 'void, DNP'}
    bets = night(site, market)
    lines = [f"{b['player']} {side(b)} {b['line']:g} {stat(b)}: " + (f"{b['points']:g}, " if b.get('points') is not None else '')
             + word[b['result']] for b in bets]
    return fit(f"The Noon Line · {dict(MODELS)[market]} results · {day_label(site['date'])}", lines,
               [f"Night: {record(bets, pct=False)}", *records_tail(site, market, before=False), '', TAGS_RESULTS])


def oauth_header(method, url, keys, params=None):
    """OAuth 1.0a (HMAC-SHA1) header. A JSON body is not part of the signature; `params` (query or form fields)
    would be (used to check it against the worked example in X's OAuth docs, signature hCtSmYh+iHYCEqBWrE7C7hYmtUk=)."""
    q = lambda s: urllib.parse.quote(str(s), safe='~')
    p = {'oauth_consumer_key': keys['X_API_KEY'], 'oauth_nonce': secrets.token_hex(16),
         'oauth_signature_method': 'HMAC-SHA1', 'oauth_timestamp': str(int(time.time())),
         'oauth_token': keys['X_ACCESS_TOKEN'], 'oauth_version': '1.0'}
    signed = {**p, **(params or {})}
    base = '&'.join([method, q(url), q('&'.join(f'{q(k)}={q(v)}' for k, v in sorted(signed.items())))])
    key = f"{q(keys['X_API_SECRET'])}&{q(keys['X_ACCESS_SECRET'])}"
    p['oauth_signature'] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return 'OAuth ' + ', '.join(f'{q(k)}="{q(v)}"' for k, v in sorted(p.items()))


def _crypt(text, decrypt=False):
    """AES-256 with the X_TOKEN_KEY secret (openssl), base64 on one line."""
    return subprocess.run(['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-salt', '-a', '-A', *(['-d'] if decrypt else []),
                           '-pass', 'env:X_TOKEN_KEY'], input=text, capture_output=True, text=True, check=True).stdout


def oauth2_bearer():
    """A fresh OAuth 2.0 access token. Uses the saved refresh token unless the X_REFRESH_TOKEN secret has changed since
    it was saved, then stores the new (rotated) refresh token before returning."""
    import requests
    seed = hashlib.sha256(os.environ['X_REFRESH_TOKEN'].encode()).hexdigest()[:16]
    saved = json.loads(_crypt(TOKEN_FILE.read_text(), decrypt=True)) if TOKEN_FILE.exists() else {}
    refresh = saved['refresh'] if saved.get('seed') == seed else os.environ['X_REFRESH_TOKEN']
    cid = os.environ['X_CLIENT_ID']
    r = requests.post(TOKEN_URL, data={'grant_type': 'refresh_token', 'refresh_token': refresh, 'client_id': cid},
                      auth=(cid, os.environ['X_CLIENT_SECRET']), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f'token refresh failed ({r.status_code}): {r.text[:200]}')
    tok = r.json()
    global SCOPES
    SCOPES = tok.get('scope', '')                       # e.g. 'tweet.write users.read tweet.read offline.access'
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(_crypt(json.dumps({'seed': seed, 'refresh': tok['refresh_token']})))
    return tok['access_token']


REDIRECT = 'https://x.com/NoonLineNBA'                     # the app's callback URI (must match it exactly)


def authorize(code, verifier):
    """Swap an authorization code (from the consent link, PKCE 'plain') for tokens that can post, and save the refresh
    token so the next post uses it (seeded to the current X_REFRESH_TOKEN secret). Returns the granted scopes."""
    import requests
    cid = os.environ['X_CLIENT_ID']
    r = requests.post(TOKEN_URL, data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT,
                                       'code_verifier': verifier, 'client_id': cid},
                      auth=(cid, os.environ['X_CLIENT_SECRET']), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"code exchange failed ({r.status_code}): {' '.join(r.text.split())[:300]}")
    tok = r.json()
    seed = hashlib.sha256(os.environ['X_REFRESH_TOKEN'].encode()).hexdigest()[:16]
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(_crypt(json.dumps({'seed': seed, 'refresh': tok['refresh_token']})))
    return tok.get('scope', '')


def connect(repo='abeilke2002/belch-bets', client_id='Ri1IdEtoWXFPckxteEFkR1RrRUQ6MTpjaQ'):
    """Run on your own computer: approve posting for @NoonLineNBA in the browser, and the new refresh token goes
    straight into the X_REFRESH_TOKEN GitHub secret. X's codes last ~30 seconds, too short for a cloud run."""
    import getpass, subprocess, webbrowser, requests
    secret = getpass.getpass('X Client Secret (from the app\'s Keys and tokens page; hidden as you paste): ').strip()
    verifier = secrets.token_urlsafe(48)
    link = ('https://x.com/i/oauth2/authorize?' + urllib.parse.urlencode({
        'response_type': 'code', 'client_id': client_id, 'redirect_uri': REDIRECT, 'state': 'noonline',
        'scope': 'tweet.read tweet.write users.read offline.access media.write', 'code_challenge': verifier,
        'code_challenge_method': 'plain'}, quote_via=urllib.parse.quote))
    print('\nOpening X. Click "Authorize app", then paste the address you land on here, right away.\n' + link + '\n')
    webbrowser.open(link)
    landed = input('Address you landed on: ').strip()
    code = urllib.parse.parse_qs(urllib.parse.urlparse(landed).query).get('code', [''])[0]
    r = requests.post(TOKEN_URL, auth=(client_id, secret), timeout=30, data={
        'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT, 'code_verifier': verifier,
        'client_id': client_id})
    if r.status_code != 200:
        print(f"Failed ({r.status_code}): {' '.join(r.text.split())[:300]}. Run it again and paste faster.")
        return
    tok = r.json()
    if 'tweet.write' not in tok.get('scope', ''):
        print('Approved, but without posting permission (scopes: ' + tok.get('scope', '') + '). Nothing saved.')
        return
    if 'media.write' not in tok.get('scope', ''):
        print('Note: approved without image permission (media.write); posts will go out as text only.')
    subprocess.run(['gh', 'secret', 'set', 'X_REFRESH_TOKEN', '-R', repo], input=tok['refresh_token'], text=True, check=True)
    print('Done: X_REFRESH_TOKEN updated with a token that can post (' + tok['scope'] + ').')


def auth_header():
    """Authorization for POST /2/tweets: OAuth 2.0 if its four secrets are set, else OAuth 1.0a, else None."""
    if all(os.environ.get(k) for k in OAUTH2):
        return 'Bearer ' + oauth2_bearer()
    keys = {k: os.environ.get(k) for k in KEYS}
    return oauth_header('POST', URL, keys) if all(keys.values()) else None


MEDIA_URL = 'https://api.x.com/2/media/upload'


def upload_image(png, auth):
    """Media id for a PNG, or None (no media.write permission, or any failure: the post goes out as text)."""
    import requests
    try:
        r = requests.post(MEDIA_URL, headers={'Authorization': auth}, timeout=60,
                          files={'media': ('card.png', png, 'image/png')}, data={'media_category': 'tweet_image'})
        if r.status_code not in (200, 201):
            print(f"X: image upload failed ({r.status_code}): {' '.join(r.text.split())[:200]}", flush=True)
            return None
        return r.json()['data']['id']
    except Exception as e:
        print(f'X: image upload failed ({type(e).__name__}: {e})', flush=True)
        return None


def post_once(key, text, image=None):
    """Post `text` (or a list of posts, as a thread) unless `key` was already posted; `image` (PNG bytes) goes on the
    first post when it uploads. Returns a one-line status; never raises (posting must not fail a run)."""
    try:
        if not (all(os.environ.get(k) for k in OAUTH2) or all(os.environ.get(k) for k in KEYS)):
            return 'X: keys not set, nothing posted'
        done = json.loads(POSTED.read_text()) if POSTED.exists() else {}
        if key in done:
            return f'X: already posted {key}'
        import requests
        auth, first, prev = auth_header(), None, None
        media = upload_image(image, auth) if image and auth.startswith('Bearer') else None
        for t in ([text] if isinstance(text, str) else text):
            body = {'text': t, **({'reply': {'in_reply_to_tweet_id': prev}} if prev else {}),
                    **({'media': {'media_ids': [media]}} if media and not prev else {})}
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
        return f"X: posted {key} ({done[key]}){' with image' if media else ''}"
    except Exception as e:
        return f'X: post failed ({type(e).__name__}: {e})'


def posted_keys():
    return json.loads(POSTED.read_text()) if POSTED.exists() else {}


def post_picks(site):
    """Noon: one post per model, bets or not (nothing on days without games or when the run failed)."""
    if not site.get('games') or site.get('status') == 'error':
        return 'X: no games or no picks today, nothing posted'
    if site['date'] in posted_keys():                   # posted before the per-model format: don't repost the day
        return f"X: already posted {site['date']}"
    return '; '.join(post_once(f"{site['date']}:{m}", picks_posts(site, m), picks_image(site, m)) for m, _ in MODELS)


def post_results(site, today=None):
    """Last night's results; on Mondays also the weekly scorecard for the 7 days before."""
    if 'results:' + site['date'] in posted_keys():        # posted before the per-model format
        out = [f"X: already posted results:{site['date']}"]
    else:
        out = [post_once(f"results:{site['date']}:{m}", results_text(site, m), results_image(site, m))
               for m, _ in MODELS if night(site, m)] \
              or ['X: no settled bets for that night, nothing posted']
    today = today or datetime.now(ZoneInfo('America/New_York')).date()
    if today.weekday() == 0:
        monday, ledger = today.isoformat(), (site.get('record') or {}).get('ledger', [])
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
                print(post_once(f"{site['date']}:{m}:update:" + hashlib.sha256('|'.join(posts).encode()).hexdigest()[:12], posts,
                                picks_image(site, m)))
            sys.exit()
        print(post_once('announce:' + hashlib.sha256(text.encode()).hexdigest()[:12], text) if text else 'X: no text given')
    elif '--dry-run' in sys.argv:
        print(picks_text(site), '\n=====')
        for m, _ in MODELS:
            print(results_text(site, m) if night(site, m) else f'results ({m}): nothing settled for that night', '\n---')
        print(week_text(site['record']['ledger'], sys.argv[-1] if sys.argv[-1][:2] == '20' else date.today().isoformat()))
    else:
        print(post_picks(site))
