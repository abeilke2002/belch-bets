"""How well do we predict teammates when a 15+ ppg player is out? Walk-forward, 2023-24 + 2024-25.

For every test game the models predict twice: with the real teammates-out information, and with it
zeroed (a no-injury counterfactual). The difference is the model's injury adjustment, compared to
how much players actually beat their no-injury projection, and to flat 5-20% boosts.
Writes reports/injury_analysis.md.
"""
import numpy as np
import pandas as pd

from build_features import teammates_out
from config import DATA, REPORTS
from regression import fit, load_rows, selected
from selection import clustered_ci

TEST = ['2023-24', '2024-25']
OUT_COLS = ['out_ppg', 'out_min', 'out_fga', 'n_out', 'out_fga_share']
BOOSTS = [0.05, 0.10, 0.15, 0.20]
STAR = 15


def star_out_games():
    """Team-games where a teammate averaging 15+ ppg (before that game) was out injured/rest."""
    g = pd.read_parquet(DATA / 'player_games.parquet')
    out, _ = teammates_out(g, g[g['played']].copy())
    stars = out[out['ppg_to_date'] >= STAR]
    return stars.groupby(['GAME_ID', 'TEAM_ID']).agg(star_out_ppg=('ppg_to_date', 'max'),
                                                    stars_out=('PLAYER_ID', 'size')).reset_index()


def walk_forward(df):
    min_f, pts_f = selected('minutes'), selected('points')
    parts = []
    for s in TEST:
        train, test = df[df['season'] < s].copy(), df[df['season'] == s].copy()
        # leave-one-season-out predicted minutes for training rows, as in regression.py
        train['pred_minutes'] = np.nan
        for t in train['season'].unique():
            m = fit(train.loc[train.season != t, min_f], train.loc[train.season != t, 'MINUTES'])
            train.loc[train.season == t, 'pred_minutes'] = m.predict(train.loc[train.season == t, min_f])
        min_model = fit(train[min_f], train['MINUTES'])
        pts_model = fit(train[pts_f], train['points'])

        cf = test.copy()
        cf[[c for c in OUT_COLS if c in cf]] = 0                # nobody out
        test['pred_minutes'] = min_model.predict(test[min_f])
        test['pred_minutes_cf'] = min_model.predict(cf[min_f])
        test['pred'] = pts_model.predict(test[pts_f])
        cf['pred_minutes'] = test['pred_minutes_cf']
        test['pred_cf'] = pts_model.predict(cf[pts_f])
        parts.append(test)
        print(f'{s}: done', flush=True)
    return pd.concat(parts)


def metrics(d, preds):
    y = d['points'].values
    rows = []
    for name, p in preds.items():
        e = np.asarray(p) - y
        rows.append({'method': name, 'RMSE': np.sqrt((e ** 2).mean()), 'MAE': np.abs(e).mean(),
                     'bias (pred - actual)': e.mean()})
    return pd.DataFrame(rows)


def best_boost(d, col):
    """Least-squares multiplier on a prediction, with a date-clustered 95% CI."""
    p, y = d[col].values, d['points'].values
    k = (p * y).sum() / (p * p).sum() - 1
    rng = np.random.default_rng(0)
    dates = d['GAME_DATE'].values
    u = np.unique(dates)
    idx = {x: np.where(dates == x)[0] for x in u}
    boot = []
    for _ in range(1000):
        rows = np.concatenate([idx[x] for x in rng.choice(u, len(u))])
        boot.append((p[rows] * y[rows]).sum() / (p[rows] ** 2).sum() - 1)
    return k, np.percentile(boot, 2.5), np.percentile(boot, 97.5)


def to_md(df):
    cols = [str(c) for c in df.columns]
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def main():
    df = load_rows()
    df = df.merge(star_out_games(), on=['GAME_ID', 'TEAM_ID'], how='left')
    df['star_out'] = df['star_out_ppg'].notna()
    res = walk_forward(df)

    # Role among teammates who played: rank by season ppg within the team-game
    res['team_rank'] = res.groupby(['GAME_ID', 'TEAM_ID'])['pts_season'].rank(ascending=False, method='first')
    res['segment'] = np.select(
        [res['team_rank'] == 1, res['pts_season'] >= 15, res['pts_season'] >= 8],
        ['top remaining scorer', 'other 15+ ppg scorers', '8-15 ppg'], '<8 ppg')

    md = [f'# Teammates of a {STAR}+ ppg player who is out (walk-forward, 2023-24 + 2024-25)\n',
          '"Model adjustment" = prediction with the injury minus the same model with nobody out. '
          '"Actual uplift" = actual points minus that no-injury prediction. If the model captured injuries '
          'well, the two would match.\n']

    star = res[res['star_out']]
    seg_rows = []
    for seg, d in [('ALL teammates', star)] + [(s, star[star.segment == s]) for s in
                                               ['top remaining scorer', 'other 15+ ppg scorers', '8-15 ppg', '<8 ppg']]:
        adj = d['pred'] - d['pred_cf']
        upl = d['points'] - d['pred_cf']
        m_u, lo_u, hi_u = clustered_ci(upl.values, d['GAME_DATE'].values)
        k, klo, khi = best_boost(d, 'pred')
        seg_rows.append({'segment': seg, 'n': len(d), 'actual pts': round(d['points'].mean(), 2),
                         'model pred': round(d['pred'].mean(), 2),
                         'model adjustment': f"{adj.mean():+.2f} ({adj.mean() / d['pred_cf'].mean():+.1%})",
                         'actual uplift': f"{m_u:+.2f} ({m_u / d['pred_cf'].mean():+.1%}) [{lo_u:+.2f}, {hi_u:+.2f}]",
                         'best boost on model': f'{k:+.1%} [{klo:+.1%}, {khi:+.1%}]'})
    md += ['## Did the model move the right amount?\n', to_md(pd.DataFrame(seg_rows)), '']

    normal = res[~res['star_out']]
    k, klo, khi = best_boost(normal, 'pred')
    md += [f'Control, games with no {STAR}+ scorer out (n={len(normal):,}): mean residual '
           f"{(normal['points'] - normal['pred']).mean():+.2f}, best boost {k:+.1%} [{klo:+.1%}, {khi:+.1%}].\n"]

    for seg, d in [('All teammates', star), ('Top remaining scorer (the Maxey case)', star[star.segment == 'top remaining scorer']),
                   ('Other 15+ ppg scorers', star[star.segment == 'other 15+ ppg scorers']),
                   ('8-15 ppg', star[star.segment == '8-15 ppg']), ('<8 ppg', star[star.segment == '<8 ppg'])]:
        preds = {'current model': d['pred'], 'model, injury ignored': d['pred_cf']}
        preds.update({f'model +{int(b * 100)}%': d['pred'] * (1 + b) for b in BOOSTS})
        preds['season avg'] = d['pts_season']
        preds.update({f'season avg +{int(b * 100)}%': d['pts_season'] * (1 + b) for b in BOOSTS})
        preds['last-5 avg'] = d['pts_5'].fillna(d['pts_season'])
        t = metrics(d, preds)
        best = t.loc[t['RMSE'].idxmin(), 'method']
        t[['RMSE', 'MAE', 'bias (pred - actual)']] = t[['RMSE', 'MAE', 'bias (pred - actual)']].round(3)
        md += [f'## {seg} (n={len(d):,}), best RMSE: {best}\n', to_md(t), '']

    # Size of the absence: a 15-20 ppg player vs a 20+ ppg star
    tier = []
    for name, m in [('15-20 ppg out', star['star_out_ppg'] < 20), ('20-25 ppg out', star['star_out_ppg'].between(20, 25)),
                    ('25+ ppg out', star['star_out_ppg'] > 25)]:
        for seg in ['top remaining scorer', 'other 15+ ppg scorers', '8-15 ppg']:
            d = star[m & (star.segment == seg)]
            if len(d) < 50:
                continue
            tier.append({'player out': name, 'teammate': seg, 'n': len(d),
                         'model adjustment': f"{(d['pred'] - d['pred_cf']).mean():+.2f}",
                         'actual uplift': f"{(d['points'] - d['pred_cf']).mean():+.2f}",
                         'best boost': f"{best_boost(d, 'pred')[0]:+.1%}"})
    md += ['## By how big the absent player is\n', to_md(pd.DataFrame(tier)), '']

    (REPORTS / 'injury_analysis.md').write_text('\n'.join(md))
    print('\n'.join(md))


if __name__ == '__main__':
    main()
