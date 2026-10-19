"""With/without-teammate splits: how a player actually did earlier this season when tonight's key absent
teammate was also out, versus when that teammate played (a box-score stand-in for lineup data).

Key teammate = the absent teammate with the highest season ppg tonight. For each player-game, using only
earlier games this season for the same team:
  wo_n        games without the key teammate
  wo_*_diff   (avg without) - (avg with) for points / FGA / minutes, shrunk toward 0 by n / (n + 5)
Tonight's absences come from whatever list is passed in (who sat, for training; the noon injury report,
for the honest backtest). Past absences are always the actual ones: they are known by then.
"""
import numpy as np
import pandas as pd

from build_features import inferred_absences

SHRINK = 5


def key_teammate(out_rows, avgs):
    """out_rows: GAME_ID, TEAM_ID, PLAYER_ID, season, GAME_DATE -> highest-ppg absent player per team-game."""
    x = pd.merge_asof(out_rows.sort_values('GAME_DATE'), avgs.sort_values('GAME_DATE'), on='GAME_DATE',
                      by=['PLAYER_ID', 'season'], allow_exact_matches=False).dropna(subset=['ppg'])
    x = x.sort_values('ppg', ascending=False).drop_duplicates(['GAME_ID', 'TEAM_ID'])
    return x[['GAME_ID', 'TEAM_ID', 'PLAYER_ID', 'ppg']].rename(columns={'PLAYER_ID': 'key_id', 'ppg': 'key_ppg'})


def compute(g, played, out_rows, avgs):
    keys = key_teammate(out_rows, avgs)
    absent = inferred_absences(g)
    absent_games = absent.groupby('PLAYER_ID')['GAME_ID'].apply(set).to_dict()

    rows = played[['PLAYER_ID', 'GAME_ID', 'TEAM_ID', 'season', 'GAME_DATE', 'points', 'fieldGoalsAttempted',
                   'MINUTES']].merge(keys, on=['GAME_ID', 'TEAM_ID'], how='left')
    rows = rows.sort_values(['PLAYER_ID', 'GAME_DATE'])
    out = []
    for (pid, season, team), grp in rows.groupby(['PLAYER_ID', 'season', 'TEAM_ID'], sort=False):
        gids = grp['GAME_ID'].values
        stats = grp[['points', 'fieldGoalsAttempted', 'MINUTES']].values
        for i, key in enumerate(grp['key_id'].values):
            if np.isnan(key) or i == 0:
                out.append((pid, gids[i], 0, 0.0, 0.0, 0.0)); continue
            key_out = absent_games.get(int(key), set())
            without = np.array([gid in key_out for gid in gids[:i]])
            n_wo, n_w = without.sum(), (~without).sum()
            if n_wo == 0 or n_w == 0:
                out.append((pid, gids[i], int(n_wo), 0.0, 0.0, 0.0)); continue
            diff = stats[:i][without].mean(0) - stats[:i][~without].mean(0)
            w = n_wo / (n_wo + SHRINK)
            out.append((pid, gids[i], int(n_wo), *(diff * w)))
    return pd.DataFrame(out, columns=['PLAYER_ID', 'GAME_ID', 'wo_n', 'wo_pts_diff', 'wo_fga_diff', 'wo_min_diff'])
