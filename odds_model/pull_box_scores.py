"""Pull regular-season traditional box scores + game info for a season via nba_api.

Resumable: games already in the output CSV are skipped.

    python pull_box_scores.py --season 2025-26
"""
import argparse
import time

import pandas as pd
from nba_api.stats.endpoints import boxscoretraditionalv3, leaguegamefinder

from config import CSV_DIR


def get_game_info(season, season_type='Regular Season'):
    finder = leaguegamefinder.LeagueGameFinder(season_nullable=season, league_id_nullable='00',
                                               season_type_nullable=season_type, timeout=60)
    return finder.get_data_frames()[0]


def get_box(game_id):
    df = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id, timeout=60) \
        .player_stats.get_data_frame()
    return df.rename(columns={'personId': 'PLAYER_ID', 'gameId': 'GAME_ID', 'teamId': 'TEAM_ID'})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', default='2025-26')
    args = ap.parse_args()
    tag = str(int(args.season[:4]) + 1)            # 2025-26 -> 2026, matching 2025_all_box.csv
    box_path = CSV_DIR / f'{tag}_all_box.csv'
    info_path = CSV_DIR / f'game_info_{tag}.csv'

    info = get_game_info(args.season)
    if info.empty:
        print(f'{args.season}: no games played yet')
        return
    info.to_csv(info_path, index=False)
    game_ids = sorted(info['GAME_ID'].unique())

    done = set()
    if box_path.exists():
        done = set(pd.read_csv(box_path, usecols=['GAME_ID'], dtype={'GAME_ID': str})['GAME_ID']
                   .str.lstrip('0'))
    todo = [g for g in game_ids if g.lstrip('0') not in done]
    print(f'{args.season}: {len(game_ids)} games, {len(todo)} to pull')

    fails = cooldowns = 0
    for i, game_id in enumerate(todo, 1):
        try:
            df = get_box(game_id)
        except Exception as e:
            fails += 1
            print(f'  {game_id} failed ({type(e).__name__}); {fails} in a row', flush=True)
            if fails >= 3:
                cooldowns += 1
                if cooldowns > 3:
                    print('stats.nba.com is still refusing requests; stopping. Rerun later to resume.')
                    break
                print(f'  cooling down 10 minutes (cool-down {cooldowns} of 3)', flush=True)
                time.sleep(600)
                fails = 0
            continue
        fails = cooldowns = 0
        df.to_csv(box_path, mode='a', header=not box_path.exists(), index=False)
        if i % 50 == 0:
            print(f'  {i}/{len(todo)}', flush=True)
        time.sleep(2)

    print(f'Saved {box_path.name} and {info_path.name}')


if __name__ == '__main__':
    main()
