"""Post the day's bets to X after the noon picks run (daily_pipeline.py calls post_picks).

Needs four GitHub secrets from the X developer app (User authentication, Read and write):
X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET. Without them nothing is posted.
One post per day at most (data/live/x_posted.json); no post on days without a bet; no site link (the site is private,
and a link costs more per post).

    python post_x.py --dry-run       # print what today's post would say
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.parse
from datetime import date

from config import DATA

URL = 'https://api.x.com/2/tweets'
POSTED = DATA / 'live' / 'x_posted.json'
KEYS = ['X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_SECRET']
LIMIT = 280


def text_for(site):
    """'Belch Bets · Tue Oct 27' then one line per bet, best edge first, trimmed to fit 280 characters."""
    day = date.fromisoformat(site['date'])
    head = f"Belch Bets · {day:%a %b} {day.day}"
    bets = sorted(site.get('picks') or [], key=lambda p: -p['edge'])
    line = lambda p: f"{p['player']} {'O' if p['side'] == 'OVER' else 'U'} {p['line']:g} ({p['price']:+d} {p['book']})"
    stake = f"{bets[0]['stake']:g}u each" if len(bets) > 1 else f"{bets[0]['stake']:g}u"
    for k in range(len(bets), 0, -1):
        more = f'\n+{len(bets) - k} more' if k < len(bets) else ''
        text = '\n'.join([head, '', *map(line, bets[:k])]) + more + f'\n\n{stake}'
        if len(text) <= LIMIT:
            return text
    return head


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


def post_picks(site):
    """Post today's bets once. Returns a one-line status; never raises (posting must not fail the picks run)."""
    try:
        if not site.get('picks'):
            return 'X: no bets today, nothing posted'
        keys = {k: os.environ.get(k) for k in KEYS}
        if not all(keys.values()):
            return 'X: keys not set, nothing posted'
        done = json.loads(POSTED.read_text()) if POSTED.exists() else {}
        if site['date'] in done:
            return f"X: already posted for {site['date']}"
        import requests
        r = requests.post(URL, json={'text': text_for(site)}, timeout=30,
                          headers={'Authorization': oauth_header('POST', URL, keys)})
        if r.status_code != 201:
            return f'X: post failed ({r.status_code}): {r.text[:200]}'
        done[site['date']] = r.json()['data']['id']
        POSTED.parent.mkdir(exist_ok=True)
        POSTED.write_text(json.dumps(done, indent=1))
        return f"X: posted {done[site['date']]}"
    except Exception as e:
        return f'X: post failed ({type(e).__name__}: {e})'


if __name__ == '__main__':
    site = json.loads((DATA / 'site' / 'picks.json').read_text())
    if '--dry-run' in sys.argv:
        print(text_for(site) if site.get('picks') else 'no bets today')
    else:
        print(post_picks(site))
