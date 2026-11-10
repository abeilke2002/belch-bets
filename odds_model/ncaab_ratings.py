"""Team ratings as of each game day, from earlier games only, and the margin they predict.

    python ncaab_ratings.py --tune      # pick half-life / prior strength / carry-over on 2021-22 and 2022-23 (margin error)
    python ncaab_ratings.py             # -> data/ncaab_preds.parquet with the chosen settings

Model (one row per team per game, points per 100 possessions):  eff = mu + O[team] - D[opp] + hca * loc
and pace (one row per game):                                     poss = mu_p + P[team] + P[opp]
loc is +1 home, -1 away, 0 neutral. Fit each day by weighted ridge on that season's games before the day: weights halve
every HALF days, and every rating is pulled toward its prior (last season's final rating x CARRY) with strength LAM
(in games). Prediction for home h vs away a: margin = poss * (eff_h - eff_a) / 100, total = poss * (eff_h + eff_a) / 100.
Torvik's own adjusted numbers are not used: they rate opponents by their end-of-season strength.
"""
import argparse
import itertools

import numpy as np
import pandas as pd
import scipy.sparse as sp

from config import DATA

DEFAULT = {'half': 1000.0, 'lam': 3.0, 'carry': 0.85}      # tuned on 2021-22 and 2022-23 (margin error)


def fit(games, teams, asof, prior, half, lam):
    """Ratings from `games` (rows before `asof`), pulled toward `prior` ({'mu','hca','O','D','mu_p','P'})."""
    n, idx = len(teams), {t: i for i, t in enumerate(teams)}
    g = games
    age = (asof - g['date']).dt.days.values.astype(float)
    w = 0.5 ** (age / half) if len(g) else np.zeros(0)
    hi, ai = g['team'].map(idx).values, g['opp'].map(idx).values
    loc = np.where(g['loc'].values == 'H', 1.0, 0.0)
    m = len(g)
    # efficiency: params [mu, hca, O(n), D(n)]
    r = np.arange(2 * m)
    team = np.r_[hi, ai]; opp = np.r_[ai, hi]
    L = np.r_[loc, -loc]
    y = np.r_[100 * g['pts'].values / g['poss'].values, 100 * g['opp_pts'].values / g['poss'].values]
    ww = np.r_[w, w]
    X = sp.csr_matrix((np.r_[np.ones(2 * m), L, np.ones(2 * m), -np.ones(2 * m)],
                       (np.r_[r, r, r, r], np.r_[np.zeros(2 * m, int), np.ones(2 * m, int), 2 + team, 2 + n + opp])),
                      shape=(2 * m, 2 + 2 * n))
    th0 = np.r_[prior['mu'], prior['hca'], prior['O'], prior['D']]
    pen = np.r_[1e-3, 1e-3, np.full(2 * n, lam)]
    A = (X.T @ sp.diags(ww) @ X).toarray() + np.diag(pen)
    th = np.linalg.solve(A, X.T @ (ww * y) + pen * th0)
    # pace: params [mu_p, P(n)]
    Xp = sp.csr_matrix((np.ones(3 * m), (np.tile(np.arange(m), 3), np.r_[np.zeros(m, int), 1 + hi, 1 + ai])),
                       shape=(m, 1 + n))
    ph0 = np.r_[prior['mu_p'], prior['P']]
    penp = np.r_[1e-3, np.full(n, lam)]
    Ap = (Xp.T @ sp.diags(w) @ Xp).toarray() + np.diag(penp)
    ph = np.linalg.solve(Ap, Xp.T @ (w * g['poss'].values) + penp * ph0)
    return {'mu': th[0], 'hca': th[1], 'O': th[2:2 + n], 'D': th[2 + n:], 'mu_p': ph[0], 'P': ph[1:]}


def carry(final, teams_prev, teams, c):
    """Next season's prior: last season's ratings x c (new teams start average)."""
    pos = {t: i for i, t in enumerate(teams_prev)}
    get = lambda arr: np.array([arr[pos[t]] * c if t in pos else 0.0 for t in teams])
    return {'mu': final['mu'], 'hca': final['hca'], 'O': get(final['O']), 'D': get(final['D']),
            'mu_p': final['mu_p'], 'P': get(final['P'])}


def predict(r, idx, home, away, loc):
    h, a = np.array([idx[t] for t in home]), np.array([idx[t] for t in away])
    L = np.where(loc == 'H', 1.0, np.where(loc == 'A', -1.0, 0.0))
    eh = r['mu'] + r['O'][h] - r['D'][a] + r['hca'] * L
    ea = r['mu'] + r['O'][a] - r['D'][h] - r['hca'] * L
    poss = r['mu_p'] + r['P'][h] + r['P'][a]
    return poss * (eh - ea) / 100, poss * (eh + ea) / 100, poss


def run(tv, games, seasons, half, lam, carry_):
    c = carry_
    """Pre-game predictions for every matched game in `seasons` (walking through each season day by day)."""
    out = []
    order = sorted(tv['season'].unique())
    teams_prev, final = None, None
    for s in order:
        t = tv[tv['season'] == s].sort_values('date')
        teams = sorted(set(t['team']) | set(t['opp']))
        idx = {x: i for i, x in enumerate(teams)}
        prior = carry(final, teams_prev, teams, c) if final else \
            {'mu': 104.0, 'hca': 1.5, 'O': np.zeros(len(teams)), 'D': np.zeros(len(teams)), 'mu_p': 68.0, 'P': np.zeros(len(teams))}
        if s in seasons:
            gs = games[games['season'] == s]
            gs = gs[gs['t_home'].isin(idx) & gs['t_away'].isin(idx)]
            gp = pd.concat([t['team'], t['opp']]).to_frame('team').assign(date=pd.concat([t['date'], t['date']]))
            for d, day in gs.groupby('date'):
                r = fit(t[t['date'] < d], teams, d, prior, half, lam)
                mg, tot, poss = predict(r, idx, day['t_home'].values, day['t_away'].values, day['loc'].values)
                before = gp[gp['date'] < d]['team'].value_counts()
                out.append(day[['event_id']].assign(pred_margin=mg, pred_total=tot, pred_poss=poss,
                                                    gp_home=day['t_home'].map(before).fillna(0).values,
                                                    gp_away=day['t_away'].map(before).fillna(0).values,
                                                    hca=r['hca']))
        end = t['date'].max() + pd.Timedelta(days=1)
        final, teams_prev = fit(t, teams, end, prior, half, lam), teams
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tune', action='store_true')
    args = ap.parse_args()
    tv = pd.read_parquet(DATA / 'ncaab_torvik.parquet')
    games = pd.read_parquet(DATA / 'ncaab_games.parquet')
    games['margin'] = games['home_pts'] - games['away_pts']
    if args.tune:
        tune = ['2021-22', '2022-23']
        rows = []
        for half, lam, c in itertools.product([20, 45, 90, 1000], [3, 8, 20], [0.5, 0.7, 0.85]):
            p = run(tv[tv['season'] <= '2022-23'], games, tune, half, lam, c).merge(games[['event_id', 'margin', 'spread']])
            rows.append({'half': half, 'lam': lam, 'carry': c, 'mae': (p['margin'] - p['pred_margin']).abs().mean(),
                         'mae_market': (p['margin'] + p['spread']).abs().mean()})
            print(rows[-1], flush=True)
        print(pd.DataFrame(rows).sort_values('mae').head(8).round(3).to_string(index=False))
        return
    p = run(tv, games, sorted(games['season'].unique()), DEFAULT['half'], DEFAULT['lam'], DEFAULT['carry'])
    p.to_parquet(DATA / 'ncaab_preds.parquet')
    m = p.merge(games[['event_id', 'season', 'margin', 'spread']])
    print(m.groupby('season').apply(lambda x: pd.Series({'games': len(x), 'model MAE': (x.margin - x.pred_margin).abs().mean(),
                                                         'market MAE': (x.margin + x.spread).abs().mean()})).round(2))


if __name__ == '__main__':
    main()
