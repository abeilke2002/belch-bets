"""Post to X: the day's bets after the noon picks run, last night's results after the 9 AM results run.

daily_pipeline.py calls post_picks (picks mode) and post_results (results mode) once the site is published.
Credentials (GitHub secrets), either kind; without them nothing is posted:
  OAuth 2.0 (what X's developer console issues now): X_CLIENT_ID, X_CLIENT_SECRET, X_REFRESH_TOKEN (the refresh token
    from "Generate" on the app's Access Token, Read and write) and X_TOKEN_KEY (any long random string). X access
    tokens last 2 hours and every refresh token works once, so each post refreshes and keeps the new refresh token
    encrypted with X_TOKEN_KEY in data/live/x_token.enc (committed by the run like the rest of data/live). Setting a
    new X_REFRESH_TOKEN secret (re-authorising) takes precedence over the saved one.
  OAuth 1.0a: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET.
Every bet is reported, wins and losses, with the season record on both posts. Each post goes out once
(data/live/x_posted.json); nothing on days without a bet; results only once every bet of the night is settled;
no site link (the site is private, and a link costs more per post).

    python post_x.py --dry-run       # print what today's two posts would say
    ANNOUNCE='text' python post_x.py --announce     # one-off post (the workflow's 'announce' mode)
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
from datetime import date

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


def picks_text(site):
    """Today's bets, best edge first, with the stake and the season record so far."""
    bets = sorted(site.get('picks') or [], key=lambda p: -p['edge'])
    lines = [f"{p['player']} {side(p)} {p['line']:g} ({p['price']:+d} {p['book']})" for p in bets]
    ledger = [b for b in (site.get('record') or {}).get('ledger', []) if b['date'] < site['date']]
    tail = [f"{bets[0]['stake']:g}u each" if len(bets) > 1 else f"{bets[0]['stake']:g}u"]
    if any(b.get('result') in SETTLED for b in ledger):
        tail.append(f"Season: {record(ledger)}")
    return fit(f"The Noon Line · {day_label(site['date'])}", lines, tail)


def night(site):
    """The page day's bets from the ledger, or [] if none or any is still unsettled."""
    bets = [b for b in (site.get('record') or {}).get('ledger', []) if b['date'] == site['date']]
    return bets if bets and all(b.get('result') in SETTLED for b in bets) else []


def results_text(site):
    """Every bet from the night with its points and result, the night's total and the season's."""
    word = {'win': 'W', 'loss': 'L', 'push': 'push', 'void': 'void, DNP'}
    bets = night(site)
    lines = [f"{b['player']} {side(b)} {b['line']:g}: " + (f"{b['points']:g} pts, " if b.get('points') is not None else '')
             + word[b['result']] for b in bets]
    ledger = [b for b in site['record']['ledger'] if b['date'] <= site['date']]
    return fit(f"The Noon Line results · {day_label(site['date'])}", lines,
               [f"Night: {record(bets, pct=False)}", f"Season: {record(ledger)}"])


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


def auth_header():
    """Authorization for POST /2/tweets: OAuth 2.0 if its four secrets are set, else OAuth 1.0a, else None."""
    if all(os.environ.get(k) for k in OAUTH2):
        return 'Bearer ' + oauth2_bearer()
    keys = {k: os.environ.get(k) for k in KEYS}
    return oauth_header('POST', URL, keys) if all(keys.values()) else None


def post_once(key, text):
    """Post `text` unless `key` was already posted. Returns a one-line status; never raises (posting must not fail a run)."""
    try:
        if not (all(os.environ.get(k) for k in OAUTH2) or all(os.environ.get(k) for k in KEYS)):
            return 'X: keys not set, nothing posted'
        done = json.loads(POSTED.read_text()) if POSTED.exists() else {}
        if key in done:
            return f'X: already posted {key}'
        import requests
        r = requests.post(URL, json={'text': text}, timeout=30, headers={'Authorization': auth_header()})
        if r.status_code != 201:
            scope = f' [token scopes: {SCOPES}]' if SCOPES is not None else ''
            return f"X: post failed ({r.status_code}): {' '.join(r.text.split())[:300]}{scope}"
        done[key] = r.json()['data']['id']
        POSTED.parent.mkdir(exist_ok=True)
        POSTED.write_text(json.dumps(done, indent=1))
        return f'X: posted {key} ({done[key]})'
    except Exception as e:
        return f'X: post failed ({type(e).__name__}: {e})'


def post_picks(site):
    if not site.get('picks'):
        return 'X: no bets today, nothing posted'
    return post_once(site['date'], picks_text(site))          # key stays the bare date (posts made before results existed)


def post_results(site):
    if not night(site):
        return 'X: no settled bets for that night, nothing posted'
    return post_once('results:' + site['date'], results_text(site))


if __name__ == '__main__':
    site = json.loads((DATA / 'site' / 'picks.json').read_text())
    if '--authorize' in sys.argv:                         # workflow 'xauth' mode: $ANNOUNCE = "<code> <verifier>"
        code, verifier = os.environ.get('ANNOUNCE', '').split()
        print('X: authorized, token scopes:', authorize(code, verifier))
    elif '--announce' in sys.argv:                          # one-off post (workflow 'announce' mode), text from $ANNOUNCE
        text = os.environ.get('ANNOUNCE', '').strip()
        print(post_once('announce:' + hashlib.sha256(text.encode()).hexdigest()[:12], text) if text else 'X: no text given')
    elif '--dry-run' in sys.argv:
        print(picks_text(site) if site.get('picks') else 'picks: no bets today', '\n---')
        print(results_text(site) if night(site) else 'results: nothing settled for that night')
    else:
        print(post_picks(site))
