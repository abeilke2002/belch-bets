"""Post to X: the day's bets after the noon picks run, last night's results after the 9 AM results run.

daily_pipeline.py calls post_picks (picks mode) and post_results (results mode) once the site is published.
Needs four GitHub secrets from the X developer app (User authentication, Read and write):
X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET. Without them nothing is posted.
Every bet is reported, wins and losses, with the season record on both posts. Each post goes out once
(data/live/x_posted.json); nothing on days without a bet; results only once every bet of the night is settled;
no site link (the site is private, and a link costs more per post).

    python post_x.py --dry-run       # print what today's two posts would say
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
    return fit(f"Belch Bets · {day_label(site['date'])}", lines, tail)


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
    return fit(f"Belch Bets results · {day_label(site['date'])}", lines,
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


def post_once(key, text):
    """Post `text` unless `key` was already posted. Returns a one-line status; never raises (posting must not fail a run)."""
    try:
        keys = {k: os.environ.get(k) for k in KEYS}
        if not all(keys.values()):
            return 'X: keys not set, nothing posted'
        done = json.loads(POSTED.read_text()) if POSTED.exists() else {}
        if key in done:
            return f'X: already posted {key}'
        import requests
        r = requests.post(URL, json={'text': text}, timeout=30, headers={'Authorization': oauth_header('POST', URL, keys)})
        if r.status_code != 201:
            return f'X: post failed ({r.status_code}): {r.text[:200]}'
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
    if '--dry-run' in sys.argv:
        print(picks_text(site) if site.get('picks') else 'picks: no bets today', '\n---')
        print(results_text(site) if night(site) else 'results: nothing settled for that night')
    else:
        print(post_picks(site))
