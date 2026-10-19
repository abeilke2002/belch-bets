"""Thin Odds API v4 client with retries, credit logging and spend guards."""
import csv
import datetime as dt
import time

import requests

from config import API_KEY, CREDIT_FLOOR, DATA

BASE = 'https://api.the-odds-api.com/v4'
LOG = DATA / 'pull_log.csv'


class CreditLimit(Exception):
    pass


class OddsAPI:
    def __init__(self, key=API_KEY, floor=CREDIT_FLOOR, max_credits=None):
        if not key:
            raise SystemExit('No Odds API key found: save it to odds_model/.odds_api_key (or set ODDS_API_KEY).')
        self.key, self.floor, self.max_credits = key, floor, max_credits
        self.spent = 0
        self.remaining = None
        self.session = requests.Session()

    def _check(self, expected):
        if self.max_credits is not None and self.spent + expected > self.max_credits:
            raise CreditLimit(f'--max-credits {self.max_credits} reached (spent {self.spent})')
        if self.remaining is not None and self.remaining - expected < self.floor:
            raise CreditLimit(f'credit floor {self.floor} reached (remaining {self.remaining})')

    def get(self, path, expected_cost=1, **params):
        """GET path; returns parsed JSON, or None for 404/422 (e.g. no data at that timestamp)."""
        self._check(expected_cost)
        params['apiKey'] = self.key
        for attempt in range(6):
            try:
                r = self.session.get(BASE + path, params=params, timeout=30)
            except requests.RequestException:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            break
        else:
            raise RuntimeError(f'giving up on {path}')

        last = int(r.headers.get('x-requests-last') or 0)
        if r.headers.get('x-requests-remaining') is not None:
            self.remaining = int(float(r.headers['x-requests-remaining']))
        self.spent += last
        self._log(path, params.get('date', ''), r.status_code, last)

        if r.status_code == 401:
            raise SystemExit('Odds API rejected the key (401).')
        if r.status_code in (404, 422):
            return None
        r.raise_for_status()
        return r.json()

    def _log(self, path, date, status, last):
        new = not LOG.exists()
        with open(LOG, 'a', newline='') as f:
            w = csv.writer(f)
            if new:
                w.writerow(['logged_at', 'path', 'date_param', 'status', 'cost', 'remaining'])
            w.writerow([dt.datetime.now().isoformat(timespec='seconds'), path, date, status, last,
                        self.remaining])
