"""Can the minutes model see a bench player's role jump coming? New pre-game inputs, tested walk-forward.

  slot_shift_min   rotation slot tonight vs with everyone healthy: players ranked by season mpg, with and
                   without tonight's absent teammates; the move is valued with a league minutes-by-slot
                   curve (e.g. 9th -> 6th is worth the gap between those slots' typical minutes)
  slot_shift_new   the same, vs his usual slot in earlier games this season (only the new part)
  out_min_pos      minutes per game of absent teammates who play his position
  new_out_min      absent teammates' minutes beyond what was typically missing in his earlier games
Writes reports/role_test.md.
"""
import numpy as np
import pandas as pd

from build_features import inferred_absences, load_positions
from config import DATA, REPORTS
from regression import TEST_SEASONS, fit, load_rows, selected

NEW = ['slot_shift_min', 'slot_shift_new', 'out_min_pos', 'new_out_min']
CURVE_SEASONS = ['2018-19', '2019-20', '2020-21', '2021-22']     # before every test season


def mpg_asof(g):
    """Season minutes per game strictly before each date, per player-season (as teammates_out does)."""
    p = g[g['played']].sort_values('GAME_DATE')[['PLAYER_ID', 'season', 'GAME_DATE', 'MINUTES']].copy()
    p['mpg'] = p.groupby(['PLAYER_ID', 'season'])['MINUTES'].transform(lambda x: x.expanding().mean())
    return p[['PLAYER_ID', 'season', 'GAME_DATE', 'mpg']]


def attach_mpg(rows, mpg):
    return pd.merge_asof(rows.sort_values('GAME_DATE'), mpg, on='GAME_DATE', by=['PLAYER_ID', 'season'],
                         allow_exact_matches=False)


def role_features(g, out=None):
    """Per (PLAYER_ID, GAME_ID) for available players. out: absent rows (default: inferred actual absences)."""
    mpg = mpg_asof(g)
    pos = load_positions().set_index('PLAYER_ID')['pos']
    out = inferred_absences(g) if out is None else out
    avail = g[g['played'] | g['cd_dnp']][['PLAYER_ID', 'season', 'GAME_ID', 'TEAM_ID', 'GAME_DATE', 'played',
                                           'MINUTES']]
    a = attach_mpg(avail, mpg).assign(is_out=False)
    out = out if 'weight' in out else out.assign(weight=1.0)
    o = attach_mpg(out[['PLAYER_ID', 'season', 'GAME_ID', 'TEAM_ID', 'GAME_DATE', 'weight']], mpg) \
        .assign(is_out=True).rename(columns={'weight': 'w'})
    both = pd.concat([a, o], ignore_index=True)
    both['m'] = both['mpg'].fillna(0)
    key = ['GAME_ID', 'TEAM_ID']
    both['rank_all'] = both.groupby(key)['m'].rank(ascending=False, method='first')
    a = both[~both['is_out']].copy()
    a['rank_active'] = a.groupby(key)['m'].rank(ascending=False, method='first')

    # league curve: average minutes played by active-rank slot
    c = a[a['season'].isin(CURVE_SEASONS) & a['played']]
    curve = c.groupby('rank_active')['MINUTES'].mean().reindex(range(1, 21)).ffill().fillna(0)
    at = lambda r: np.interp(r, curve.index, curve.values)
    # partial absences (Questionable at half): move only part of the way up
    a['slot_shift_min'] = at(a['rank_active']) - at(a['rank_all'])
    a = a.sort_values('GAME_DATE')
    usual = a.groupby(['PLAYER_ID', 'season'])['rank_active'].transform(lambda x: x.shift(1).expanding().mean())
    a['slot_shift_new'] = at(a['rank_active']) - at(usual.fillna(a['rank_active']))

    o['pos'] = o['PLAYER_ID'].map(pos)
    a['pos'] = a['PLAYER_ID'].map(pos)
    o['x'] = o['mpg'].fillna(0) * o['w']
    po = o.groupby(key + ['pos'])['x'].sum().rename('out_min_pos').reset_index()
    a = a.merge(po, on=key + ['pos'], how='left')
    a['out_min_pos'] = a['out_min_pos'].fillna(0)
    tot = o.groupby(key)['x'].sum().rename('om').reset_index()
    a = a.merge(tot, on=key, how='left').fillna({'om': 0}).sort_values('GAME_DATE')
    a['new_out_min'] = a['om'] - a.groupby(['PLAYER_ID', 'season'])['om'].transform(
        lambda x: x.shift(1).expanding().mean()).fillna(0)
    return a[['PLAYER_ID', 'GAME_ID'] + NEW], curve


def walk_forward(df, mf, pf):
    out = []
    for s in TEST_SEASONS:
        tr = df[df['season'] < s].copy()
        tr['pred_minutes'] = np.nan
        for t in tr['season'].unique():
            m = fit(tr.loc[tr['season'] != t, mf], tr.loc[tr['season'] != t, 'MINUTES'])
            tr.loc[tr['season'] == t, 'pred_minutes'] = m.predict(tr.loc[tr['season'] == t, mf])
        te = df[df['season'] == s].copy()
        te['pred_minutes'] = fit(tr[mf], tr['MINUTES']).predict(te[mf])
        te['pred_points'] = fit(tr[pf], tr['points']).predict(te[pf])
        out.append(te)
    return pd.concat(out)


def to_md(df):
    cols = [str(c) for c in df.columns]
    o = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(o + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def main():
    g = pd.read_parquet(DATA / 'player_games.parquet')
    feats, curve = role_features(g)
    print('minutes by rotation slot:', curve.head(12).round(1).tolist())
    df = load_rows().merge(feats, on=['PLAYER_ID', 'GAME_ID'], how='left')
    mf, pf = selected('minutes'), selected('points')
    base = walk_forward(df, mf, pf)
    new = walk_forward(df, mf + NEW, pf)
    lines = pd.read_parquet(DATA / 'odds_lines.parquet').merge(pd.read_parquet(DATA / 'name_map.parquet'),
                                                               on=['event_id', 'player'])
    lines = lines.dropna(subset=['PLAYER_ID', 'early_line']).astype({'PLAYER_ID': int})[['PLAYER_ID', 'GAME_ID',
                                                                                         'early_line']]
    rows = []
    for name, x in [('current', base), ('+ role features', new)]:
        x = x.merge(lines.drop_duplicates(['PLAYER_ID', 'GAME_ID']), on=['PLAYER_ID', 'GAME_ID'], how='left')
        x['me'], x['pe'] = x['MINUTES'] - x['pred_minutes'], x['points'] - x['pred_points']
        segs = {'all games': x.index == x.index,
                'bench (<15 mpg), 25+ new minutes out': (x['min_season'] < 15) & (x['new_out_min'] >= 25),
                'props: line 4+ above season avg': x['early_line'] - x['pts_season'] >= 4,
                'props: bench (<15 mpg), line 2+ above avg': (x['min_season'] < 15) & (x['early_line'] - x['pts_season'] >= 2)}
        for seg, msk in segs.items():
            y = x[msk]
            rows.append({'model': name, 'segment': seg, 'games': len(y),
                         'minutes RMSE': round(float(np.sqrt((y['me'] ** 2).mean())), 3),
                         'minutes bias (actual - pred)': round(float(y['me'].mean()), 2),
                         'points RMSE': round(float(np.sqrt((y['pe'] ** 2).mean())), 3),
                         'points bias (actual - pred)': round(float(y['pe'].mean()), 2)})
    res = pd.DataFrame(rows).sort_values(['segment', 'model'], kind='stable')
    new[['PLAYER_ID', 'GAME_ID', 'season', 'pred_minutes', 'pred_points']].to_parquet(DATA / 'role_test_preds.parquet')
    md = ['# Role-jump features for the minutes model\n', 'Walk-forward 2023-26, actual absences.\n', to_md(res), '']
    (REPORTS / 'role_test.md').write_text('\n'.join(md))
    print('\n'.join(md))


if __name__ == '__main__':
    main()
