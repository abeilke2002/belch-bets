"""Build leak-free pre-game player features from box scores -> data/player_games.parquet.

Every feature for a game uses only that player's earlier games in the same season.
DNP rows are kept (so odds can be matched and voided) but have played == False.
"""
import numpy as np
import pandas as pd

from config import BOX_FILES, CSV_DIR, DATA, GAME_INFO_FILES, SEASON_CODE

BOX_COLS = ['GAME_ID', 'TEAM_ID', 'PLAYER_ID', 'teamCity', 'teamName', 'firstName', 'familyName',
            'comment', 'minutes', 'position', 'points', 'fieldGoalsAttempted', 'freeThrowsAttempted',
            'threePointersAttempted']


def to_minutes(x):
    if pd.isna(x):
        return 0.0
    if isinstance(x, str) and ':' in x:
        m, s = x.split(':')
        return int(float(m)) + int(float(s)) / 60
    try:
        return float(x)
    except ValueError:
        return 0.0


def load_box():
    frames = [pd.read_csv(CSV_DIR / f, usecols=lambda c: c in BOX_COLS, dtype={'GAME_ID': str},
                          low_memory=False)
              for f in BOX_FILES if (CSV_DIR / f).exists()]
    box = pd.concat(frames, ignore_index=True)
    box['GAME_ID'] = box['GAME_ID'].str.lstrip('0')
    box = box[box['GAME_ID'].str[:3].isin(SEASON_CODE)]          # regular season only
    box = box.drop_duplicates(['GAME_ID', 'PLAYER_ID'])
    box['season'] = box['GAME_ID'].str[:3].map(SEASON_CODE)
    box['MINUTES'] = box['minutes'].apply(to_minutes)
    box['played'] = box['MINUTES'] > 0
    box['started'] = box['position'].fillna('').str.strip().ne('').astype(int)
    box['cd_dnp'] = ~box['played'] & box['comment'].fillna('').str.contains('Coach')

    info = pd.concat([pd.read_csv(CSV_DIR / f, dtype={'GAME_ID': str})
                      for f in GAME_INFO_FILES if (CSV_DIR / f).exists()], ignore_index=True)
    info['GAME_ID'] = info['GAME_ID'].str.lstrip('0')
    info['is_home'] = info['MATCHUP'].str.contains('vs.').astype(int)
    info = info.drop_duplicates(['GAME_ID', 'TEAM_ID'])[['GAME_ID', 'TEAM_ID', 'GAME_DATE', 'is_home']]
    box = box.merge(info, on=['GAME_ID', 'TEAM_ID'], how='left')
    missing = box['GAME_DATE'].isna().mean()
    if missing > 0:
        print(f'warning: {missing:.1%} of box rows have no GAME_DATE; dropping them')
        box = box.dropna(subset=['GAME_DATE'])
    box['GAME_DATE'] = pd.to_datetime(box['GAME_DATE'])
    box = add_opponent(box).merge(load_positions(), on='PLAYER_ID', how='left')
    return box.sort_values(['PLAYER_ID', 'GAME_DATE']).reset_index(drop=True)


POS_MAP = {'Guard': 'G', 'Guard-Forward': 'G', 'Forward': 'F', 'Forward-Guard': 'F',
           'Forward-Center': 'F', 'Center': 'C', 'Center-Forward': 'C'}


def load_positions():
    pp = pd.read_csv(CSV_DIR / 'player_position.csv')
    pp['pos'] = pp['POSITION'].map(POS_MAP)
    return pp.dropna(subset=['pos']).drop_duplicates('PLAYER_ID')[['PLAYER_ID', 'pos']]


def add_opponent(df):
    teams = df[['GAME_ID', 'TEAM_ID']].drop_duplicates()
    pairs = teams.merge(teams, on='GAME_ID', suffixes=('', '_opp'))
    pairs = pairs[pairs['TEAM_ID'] != pairs['TEAM_ID_opp']].rename(columns={'TEAM_ID_opp': 'OPP_ID'})
    return df.merge(pairs, on=['GAME_ID', 'TEAM_ID'], how='left')


def defense_history(played):
    """Running averages of points allowed (by each defense, and league-wide) through each game date,
    inclusive. lookup_defense reads them strictly before a game's date."""
    def running(df, keys):
        df = df.sort_values('GAME_DATE').copy()
        g = df.groupby(keys)['points']
        df['avg'], df['n_games'] = g.cumsum() / (g.cumcount() + 1), g.cumcount() + 1
        return df.groupby(keys + ['GAME_DATE'])[['avg', 'n_games']].last().reset_index().sort_values('GAME_DATE')

    by_pos = played.dropna(subset=['pos']).groupby(['OPP_ID', 'season', 'pos', 'GAME_ID', 'GAME_DATE'])[
        'points'].sum().reset_index()
    total = played.groupby(['OPP_ID', 'season', 'GAME_ID', 'GAME_DATE'])['points'].sum().reset_index()
    return {'opp_pos_ratio': (running(by_pos, ['OPP_ID', 'season', 'pos']), running(by_pos, ['season', 'pos'])),
            'opp_total_ratio': (running(total, ['OPP_ID', 'season']), running(total, ['season']))}


def lookup_defense(rows, hist, min_games=5):
    """rows: OPP_ID, season, pos, GAME_DATE -> defense allowed avg / league avg, both from earlier dates."""
    out = rows.reset_index().astype({'GAME_DATE': 'datetime64[ns]'}).sort_values('GAME_DATE')
    for name, (team, league) in hist.items():
        team, league = (t.astype({'GAME_DATE': 'datetime64[ns]'}) for t in (team, league))
        tk = [c for c in team.columns if c not in ('GAME_DATE', 'avg', 'n_games')]
        lk = [c for c in league.columns if c not in ('GAME_DATE', 'avg', 'n_games')]
        out = pd.merge_asof(out, team.rename(columns={'avg': 't_avg', 'n_games': 't_n'}),
                            on='GAME_DATE', by=tk, allow_exact_matches=False)
        out = pd.merge_asof(out, league[lk + ['GAME_DATE', 'avg']].rename(columns={'avg': 'l_avg'}),
                            on='GAME_DATE', by=lk, allow_exact_matches=False)
        out[name] = np.where(out['t_n'] >= min_games, out['t_avg'] / out['l_avg'], np.nan)
        out = out.drop(columns=['t_avg', 't_n', 'l_avg'])
    return out.set_index('index').sort_index()[list(hist)]


def player_features(played):
    g = played.groupby(['PLAYER_ID', 'season'], sort=False)
    played['gp'] = g.cumcount()                                   # games played before this one
    for col, name in [('points', 'pts'), ('fieldGoalsAttempted', 'fga'),
                      ('freeThrowsAttempted', 'fta'), ('MINUTES', 'min')]:
        s = g[col]
        prior_sum = s.cumsum() - played[col]
        played[f'{name}_season'] = prior_sum / played['gp'].replace(0, np.nan)
        for w in (3, 5):
            played[f'{name}_{w}'] = s.transform(lambda x: x.shift(1).rolling(w).mean())
    played['pts_std'] = g['points'].transform(lambda x: x.shift(1).expanding(3).std())
    played['start_rate'] = (g['started'].cumsum() - played['started']) / played['gp'].replace(0, np.nan)
    played['started_last'] = g['started'].shift(1)
    played['starts_5'] = g['started'].transform(lambda x: x.shift(1).rolling(5).mean())
    played['rest_days'] = g['GAME_DATE'].diff().dt.days.clip(upper=10)

    # Previous season's ppg (only when that season directly precedes this one)
    season_ppg = played.groupby(['PLAYER_ID', 'season'])['points'].mean().rename('prev_season_ppg')
    season_ppg = season_ppg.reset_index()
    season_ppg['season'] = season_ppg['season'].map(
        lambda s: f'{int(s[:4]) + 1}-{(int(s[:4]) + 2) % 100:02d}')
    return played.merge(season_ppg, on=['PLAYER_ID', 'season'], how='left')


def inferred_absences(box):
    """Team games each player missed while on the team. Long-term injured players are on the inactive
    list and have no box-score row at all, so absences are inferred from the schedule: every team game
    from his first appearance for the team on, where he didn't play and wasn't a coach's-decision DNP.
    After his last appearance he still counts as out (season-ending injury) unless he later appears for
    another team that season (traded or waived)."""
    tg = box[['TEAM_ID', 'season', 'GAME_ID', 'GAME_DATE']].drop_duplicates(['TEAM_ID', 'GAME_ID'])
    stints = box.groupby(['PLAYER_ID', 'season', 'TEAM_ID'])['GAME_DATE'].agg(first='min', last='max').reset_index()
    stints = stints.sort_values(['PLAYER_ID', 'season', 'first'])
    stints['moved_on'] = stints.groupby(['PLAYER_ID', 'season'])['first'].shift(-1).notna()
    span = stints.merge(tg, on=['TEAM_ID', 'season'])
    span = span[(span['GAME_DATE'] >= span['first']) &
                (~span['moved_on'] | (span['GAME_DATE'] <= span['last']))]
    available = box.loc[box['played'] | box['cd_dnp'], ['PLAYER_ID', 'GAME_ID']].assign(avail=True)
    span = span.merge(available, on=['PLAYER_ID', 'GAME_ID'], how='left')
    return span[span['avail'].isna()][['PLAYER_ID', 'season', 'GAME_ID', 'TEAM_ID', 'GAME_DATE']]


def teammates_out(box, played):
    """Season ppg/mpg/fga (before that game) of teammates who were out, summed per team-game.
    Coach's-decision DNPs are excluded: they aren't known from the injury report."""
    out = inferred_absences(box)
    ppg = played[['PLAYER_ID', 'season', 'GAME_DATE', 'points']].copy()
    ppg['ppg_to_date'] = ppg.groupby(['PLAYER_ID', 'season'])['points'].transform(
        lambda x: x.expanding().mean())
    ppg['mpg_to_date'] = played.groupby(['PLAYER_ID', 'season'])['MINUTES'].transform(
        lambda x: x.expanding().mean())
    ppg['fga_to_date'] = played.groupby(['PLAYER_ID', 'season'])['fieldGoalsAttempted'].transform(
        lambda x: x.expanding().mean())
    out = pd.merge_asof(out.sort_values('GAME_DATE'),
                        ppg.sort_values('GAME_DATE')[['PLAYER_ID', 'season', 'GAME_DATE', 'ppg_to_date',
                                                      'mpg_to_date', 'fga_to_date']],
                        on='GAME_DATE', by=['PLAYER_ID', 'season'], allow_exact_matches=False)
    team_out = out.groupby(['GAME_ID', 'TEAM_ID']).agg(out_ppg=('ppg_to_date', 'sum'),
                                                       out_min=('mpg_to_date', 'sum'),
                                                       out_fga=('fga_to_date', 'sum'),
                                                       n_out=('PLAYER_ID', 'size')).reset_index()
    return out, team_out


POS_CODE = {'G': 0, 'F': 1, 'C': 2}
ROTATION_MPG = 5


def position_absences(rows):
    """Minutes missing at each position and who is left to play them. `rows`: every rostered player of each
    team-game with GAME_ID, TEAM_ID, pos, mpg (season to date) and w (0 available .. 1 out). Per
    (GAME_ID, TEAM_ID, pos): out_min_pos (absent teammates' mpg, weighted), n_active_pos (rotation players,
    5+ mpg, still available, counting 1 - w) and n_rot_pos (rotation players whether out or not, for the
    nobody-out baseline). Shared by build_features, predict_today and (ported) site/model.js."""
    r = rows.assign(_out=rows['mpg'].fillna(0) * rows['w'], _rot=(rows['mpg'] >= ROTATION_MPG).astype(float))
    r['_act'] = r['_rot'] * (1 - r['w'])
    return r.groupby(['GAME_ID', 'TEAM_ID', 'pos']).agg(out_min_pos=('_out', 'sum'), n_active_pos=('_act', 'sum'),
                                                         n_rot_pos=('_rot', 'sum')).reset_index()


def finish_position(df):
    """Fill in for players without a position or teammates there, and add pos_vacancy (missing minutes per
    rotation player left at the position: about 43 for Clint Capela on 2026-10-28, Sengun and Adams out) and
    pos_code (G/F/C as 0/1/2)."""
    df['out_min_pos'] = df['out_min_pos'].fillna(0)
    df['n_active_pos'] = df['n_active_pos'].fillna(1).clip(lower=1)
    df['n_rot_pos'] = df['n_rot_pos'].fillna(1).clip(lower=1)
    df['pos_vacancy'] = df['out_min_pos'] / df['n_active_pos']
    df['pos_code'] = df['pos'].map(POS_CODE)
    return df


def team_fga_per_game(played):
    """Team FGA per game in the season before each game (for the share of shots freed up)."""
    tf = played.groupby(['TEAM_ID', 'season', 'GAME_ID', 'GAME_DATE'])['fieldGoalsAttempted'].sum() \
        .reset_index().sort_values('GAME_DATE')
    g = tf.groupby(['TEAM_ID', 'season'])['fieldGoalsAttempted']
    tf['team_fga_pg'] = (g.cumsum() - tf['fieldGoalsAttempted']) / g.cumcount().replace(0, np.nan)
    return tf[['GAME_ID', 'TEAM_ID', 'GAME_DATE', 'team_fga_pg']]


def add_redistribution(df):
    """Shots freed by absent teammates, split by each remaining player's share of the remaining shots.
    Uses only season-to-date averages, so it is known before tip-off (shared with predict_today)."""
    df = df.copy()
    remaining = (df['team_fga_pg'] - df['out_fga']).clip(lower=0.5 * df['team_fga_pg'])
    df['usage_share'] = df['fga_season'] / df['team_fga_pg']
    df['exp_extra_fga'] = df['out_fga'] * df['fga_season'] / remaining
    df['exp_extra_pts'] = df['exp_extra_fga'] * df['pts_season'] / df['fga_season'].where(df['fga_season'] > 0)
    df.loc[df['out_fga'] == 0, ['exp_extra_fga', 'exp_extra_pts']] = 0.0
    # Only the NEW part of an absence: shots freed tonight beyond what was typically missing in his
    # earlier games this season (already baked into his averages). Negative when a teammate returns.
    if 'out_fga_season_avg' in df:
        pts_per_fga = df['pts_season'] / df['fga_season'].where(df['fga_season'] > 0)
        for src, name in [('out_fga_season_avg', 'new'), ('out_fga_5', 'recent')]:
            delta = df['out_fga'] - df[src].fillna(0)
            df[f'exp_extra_fga_{name}'] = delta * df['fga_season'] / remaining
            df[f'exp_extra_pts_{name}'] = df[f'exp_extra_fga_{name}'] * pts_per_fga
    return df


def absence_features(box, cap_missed=20, cap_since=10):
    """Per played game: team games missed right before it, played games since the last absence, and
    that absence's length. A coach's-decision DNP counts as available, not absent. Gaps are counted
    within one team, so a trade isn't an absence. A player's first game of the season counts the
    team games before it (catches stars back from preseason injuries; rookies' late debuts too)."""
    tg = box[['TEAM_ID', 'season', 'GAME_ID', 'GAME_DATE']].drop_duplicates(['TEAM_ID', 'GAME_ID']) \
        .sort_values('GAME_DATE')
    tg['tg_idx'] = tg.groupby(['TEAM_ID', 'season']).cumcount()
    present = box[box['played'] | box['cd_dnp']][['PLAYER_ID', 'TEAM_ID', 'season', 'GAME_ID',
                                                   'GAME_DATE', 'played']]
    present = present.merge(tg[['TEAM_ID', 'GAME_ID', 'tg_idx']], on=['TEAM_ID', 'GAME_ID']) \
        .sort_values(['PLAYER_ID', 'season', 'GAME_DATE'])
    prev_idx = present.groupby(['PLAYER_ID', 'season', 'TEAM_ID'])['tg_idx'].shift(1)
    first_of_season = present.groupby(['PLAYER_ID', 'season']).cumcount() == 0
    missed = np.where(prev_idx.notna(), present['tg_idx'] - prev_idx - 1,
                      np.where(first_of_season, present['tg_idx'], 0))
    present['games_missed_before'] = np.clip(missed, 0, cap_missed)

    p = present[present['played']].copy()
    block = p.groupby(['PLAYER_ID', 'season'])['games_missed_before'].transform(lambda x: (x > 0).cumsum())
    p['games_since_return'] = p.groupby([p['PLAYER_ID'], p['season'], block]).cumcount()
    p.loc[block == 0, 'games_since_return'] = cap_since
    p['games_since_return'] = p['games_since_return'].clip(upper=cap_since)
    p['last_absence_len'] = p['games_missed_before'].where(p['games_missed_before'] > 0)
    p['last_absence_len'] = p.groupby(['PLAYER_ID', 'season'])['last_absence_len'].ffill().fillna(0)
    p.loc[block == 0, 'last_absence_len'] = 0
    return p[['PLAYER_ID', 'GAME_ID', 'games_missed_before', 'games_since_return', 'last_absence_len']]


def leakage_checks(feat, played, box):
    rows = feat[feat['played']].sample(400, random_state=0)
    by_ps = {k: v for k, v in played.groupby(['PLAYER_ID', 'season'])}
    for _, r in rows.iterrows():
        hist = by_ps[(r.PLAYER_ID, r.season)]
        prior = hist[hist['GAME_DATE'] < r.GAME_DATE]['points']
        assert len(prior) == r.gp, 'games-played count uses non-prior games'
        if len(prior):
            assert np.isclose(prior.mean(), r.pts_season), 'pts_season uses non-prior games'
        if len(prior) >= 5:
            assert np.isclose(prior.tail(5).mean(), r.pts_5), 'pts_5 is not the last 5 prior games'
        if len(prior):
            starts = hist[hist['GAME_DATE'] < r.GAME_DATE]['started']
            assert np.isclose(starts.mean(), r.start_rate), 'start_rate uses non-prior games'
    # Opponent defense: recompute a sample from games strictly before the date
    pos_rows = feat[feat['played'] & feat['opp_pos_ratio'].notna()].sample(100, random_state=1)
    for _, r in pos_rows.iterrows():
        prior = played[(played['OPP_ID'] == r.OPP_ID) & (played['season'] == r.season) &
                       (played['GAME_DATE'] < r.GAME_DATE)]
        team = prior[prior['pos'] == r.pos].groupby('GAME_ID')['points'].sum().mean()
        lg_rows = played[(played['season'] == r.season) & (played['GAME_DATE'] < r.GAME_DATE) &
                         (played['pos'] == r.pos)]
        league = lg_rows.groupby(['GAME_ID', 'OPP_ID'])['points'].sum().mean()
        assert np.isclose(team / league, r.opp_pos_ratio), 'opp_pos_ratio uses non-prior games'
    # Absences: count the team's games strictly between his previous available game and this one
    team_dates = box.drop_duplicates(['TEAM_ID', 'GAME_ID']).groupby(['TEAM_ID', 'season'])['GAME_DATE'].apply(np.sort)
    avail = box[box['played'] | box['cd_dnp']]
    by_pst = {k: v['GAME_DATE'].values for k, v in avail.groupby(['PLAYER_ID', 'season', 'TEAM_ID'])}
    for _, r in feat[feat['played']].sample(300, random_state=2).iterrows():
        mine = by_pst[(r.PLAYER_ID, r.season, r.TEAM_ID)]
        prev = mine[mine < np.datetime64(r.GAME_DATE)]
        if len(prev):
            dates = team_dates[(r.TEAM_ID, r.season)]
            gap = ((dates > prev.max()) & (dates < np.datetime64(r.GAME_DATE))).sum()
            assert min(gap, 20) == r.games_missed_before, 'games_missed_before is wrong'
    # Team FGA per game: prior games only
    for _, r in feat[feat['played'] & feat['team_fga_pg'].notna()].sample(100, random_state=3).iterrows():
        prior = played[(played['TEAM_ID'] == r.TEAM_ID) & (played['season'] == r.season) &
                       (played['GAME_DATE'] < r.GAME_DATE)]
        assert np.isclose(prior.groupby('GAME_ID')['fieldGoalsAttempted'].sum().mean(), r.team_fga_pg)
    assert not feat.duplicated(['PLAYER_ID', 'GAME_ID']).any()
    print('leakage checks passed (400 rows: season avg, last-5, gp, start rate; 100: opponent defense; '
          '300: games missed; 100: team FGA) - all use prior games only')


def main():
    box = load_box()
    played = player_features(box[box['played']].copy())
    out, team_out = teammates_out(box, played)

    # A player can never count toward his own out_ppg: out rows are DNPs, feature rows are played
    assert out.merge(played[['PLAYER_ID', 'GAME_ID']], on=['PLAYER_ID', 'GAME_ID']).empty

    feat_cols = [c for c in played.columns if c not in box.columns]
    feat = box.merge(played[['PLAYER_ID', 'GAME_ID'] + feat_cols], on=['PLAYER_ID', 'GAME_ID'],
                     how='left')
    feat = feat.merge(team_out, on=['GAME_ID', 'TEAM_ID'], how='left')
    feat[['out_ppg', 'out_min', 'out_fga', 'n_out']] = feat[['out_ppg', 'out_min', 'out_fga', 'n_out']].fillna(0)
    feat = feat.merge(team_fga_per_game(played).drop(columns='GAME_DATE'), on=['GAME_ID', 'TEAM_ID'], how='left')
    feat['out_fga_share'] = feat['out_fga'] / feat['team_fga_pg']
    feat = feat.merge(absence_features(box), on=['PLAYER_ID', 'GAME_ID'], how='left')
    # How many shots were typically missing in his earlier games (prior games only)
    played_rows = feat['played']
    pr = feat.loc[played_rows, ['PLAYER_ID', 'season', 'GAME_DATE', 'out_fga']].sort_values(['PLAYER_ID', 'GAME_DATE'])
    g = pr.groupby(['PLAYER_ID', 'season'])['out_fga']
    pr['out_fga_season_avg'] = g.transform(lambda x: x.shift(1).expanding().mean())
    pr['out_fga_5'] = g.transform(lambda x: x.shift(1).rolling(5, min_periods=1).mean())
    feat = feat.join(pr[['out_fga_season_avg', 'out_fga_5']])
    feat = add_redistribution(feat)
    # Position: absent teammates (inferred absences, weight 1) and players dressed for the game (weight 0)
    mpg = played[['PLAYER_ID', 'season', 'GAME_DATE', 'MINUTES']].copy()
    mpg['mpg'] = mpg.groupby(['PLAYER_ID', 'season'])['MINUTES'].transform(lambda x: x.expanding().mean())
    mpg = mpg.drop(columns='MINUTES').sort_values('GAME_DATE')
    dressed = box.loc[box['played'] | box['cd_dnp'], ['PLAYER_ID', 'season', 'GAME_ID', 'TEAM_ID', 'GAME_DATE']]
    rost = pd.concat([out[['PLAYER_ID', 'season', 'GAME_ID', 'TEAM_ID', 'GAME_DATE']].assign(w=1.0), dressed.assign(w=0.0)])
    rost = pd.merge_asof(rost.sort_values('GAME_DATE'), mpg, on='GAME_DATE', by=['PLAYER_ID', 'season'],
                         allow_exact_matches=False).merge(load_positions(), on='PLAYER_ID', how='left')
    feat = finish_position(feat.merge(position_absences(rost), on=['GAME_ID', 'TEAM_ID', 'pos'], how='left'))
    feat[['opp_pos_ratio', 'opp_total_ratio']] = lookup_defense(
        feat[['OPP_ID', 'season', 'pos', 'GAME_DATE']], defense_history(played))
    feat['player_name'] = feat['firstName'].fillna('') + ' ' + feat['familyName'].fillna('')
    feat = feat.drop(columns=['minutes', 'comment'])

    leakage_checks(feat, played, box)
    feat.to_parquet(DATA / 'player_games.parquet', index=False)
    print(f'saved player_games.parquet: {len(feat):,} rows, {feat["played"].sum():,} played')
    print(feat[feat.played].groupby('season').size().to_string())


if __name__ == '__main__':
    main()
