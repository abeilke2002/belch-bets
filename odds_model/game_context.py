"""Game context the projection uses besides a player's own form and his team's absences (all known at noon):

  lines      team_spread (negative = his team favored), abs_spread, total, team_implied   ESPN's number: opening
             where ESPN has it (2023-24 on), closing before; live, ESPN's number at noon
  returning  ret_min, ret_min_pos   season mpg of 10+ mpg teammates back from a reported absence: missed the team's
             previous game while on its injury report and aren't out tonight (x (1 - weight)), for the team and
             at his position. Blank before 2023-24, when there are no reports
  opponent   opp_out_min, opp_out_ppg, opp_out_min_pos   the opponent's absences tonight, weighted like ours
             (Out/Doubtful 1, Questionable 0.5), in total and at his position

Backtested in scratchpad four_features_test.py (2024-26, 3 seeds): +1.1e-4 log-loss gain over the market on every
seed and season, ~+17u. Pace (possessions per game) was tested too and added nothing.

    python game_context.py      # rebuild data/game_context.parquet (training rows; needs game_lines, noon_injuries)
"""
import numpy as np
import pandas as pd

from config import DATA

RETURN_MPG = 10
REPORT_ERA = '2023-24'
LINES = ['team_spread', 'abs_spread', 'total', 'team_implied']
RETURNING = ['ret_min', 'ret_min_pos']
OPPONENT = ['opp_out_min', 'opp_out_ppg', 'opp_out_min_pos']
FEATURES = LINES + RETURNING + OPPONENT
PATH = DATA / 'game_context.parquet'


def clean_lines(gl):
    gl = gl.copy()
    for c in ['total', 'open_total']:
        if c in gl:
            gl.loc[~gl[c].between(180, 280), c] = np.nan
    return gl


def line_features(x):
    """x has is_home, hs (home spread), total -> the four line features."""
    x['team_spread'] = np.where(x['is_home'] == 1, x['hs'], -x['hs'])
    x['abs_spread'] = x['team_spread'].abs()
    x['team_implied'] = x['total'] / 2 - x['team_spread'] / 2
    return x


def returning(rows, mpg, w, back, pos):
    """ret_min / ret_min_pos for each row. rows: PLAYER_ID, TEAM_ID, GAME_ID, pos; back: boolean per row (missed the
    previous game as a reported absence); mpg, w: per row. Each player's own minutes never count."""
    r = rows.assign(_r=np.where(back & (mpg >= RETURN_MPG), mpg * (1 - w), 0.0))
    team = r.groupby(['GAME_ID', 'TEAM_ID'])['_r'].transform('sum')
    at_pos = r.groupby(['GAME_ID', 'TEAM_ID', pos], dropna=False)['_r'].transform('sum')
    return (team - r['_r']).clip(lower=0).values, np.where(r[pos].notna(), (at_pos - r['_r']).clip(lower=0), 0.0)


def history():
    """Every (PLAYER_ID, GAME_ID) in player_games with the context features, as known at noon."""
    import q_policy_test as qp
    from build_features import inferred_absences, load_positions
    from noon_backtest import season_averages
    g = pd.read_parquet(DATA / 'player_games.parquet')
    played = g[g['played']].copy()
    rep = pd.read_parquet(DATA / 'noon_injuries.parquet')
    half = qp.absence_lists(g, played, rep)['half']
    avgs = season_averages(played)
    positions = load_positions()
    asof = lambda r: pd.merge_asof(r.sort_values('GAME_DATE'), avgs[['PLAYER_ID', 'season', 'GAME_DATE', 'mpg', 'ppg']]
                                   .sort_values('GAME_DATE'), on='GAME_DATE', by=['PLAYER_ID', 'season'],
                                   allow_exact_matches=False)
    wmap = half.groupby(['GAME_ID', 'PLAYER_ID'])['weight'].max()

    # returning: the team's players who missed its previous game while listed on that game's report
    tg = g[['TEAM_ID', 'season', 'GAME_ID', 'GAME_DATE']].drop_duplicates(['TEAM_ID', 'GAME_ID']).sort_values('GAME_DATE')
    tg['k'] = tg.groupby(['TEAM_ID', 'season']).cumcount()
    listed = set(zip(rep['GAME_ID'], rep['PLAYER_ID']))
    ab = inferred_absences(g).merge(tg[['TEAM_ID', 'GAME_ID', 'k']], on=['TEAM_ID', 'GAME_ID'])
    ab = ab[[k in listed for k in zip(ab['GAME_ID'], ab['PLAYER_ID'])]]
    back = ab.assign(k=ab['k'] + 1)[['PLAYER_ID', 'TEAM_ID', 'season', 'k']] \
             .merge(tg[['TEAM_ID', 'season', 'k', 'GAME_ID', 'GAME_DATE']], on=['TEAM_ID', 'season', 'k'])
    back = back.drop_duplicates(['GAME_ID', 'PLAYER_ID']).assign(back=True)[['GAME_ID', 'PLAYER_ID', 'TEAM_ID', 'GAME_DATE', 'season', 'back']]
    key = g[['PLAYER_ID', 'GAME_ID', 'TEAM_ID', 'OPP_ID', 'season', 'GAME_DATE', 'is_home']].drop_duplicates(['PLAYER_ID', 'GAME_ID'])
    # every rostered player of each team-game (box rows) plus returners with no box row tonight
    allr = pd.concat([key[['PLAYER_ID', 'GAME_ID', 'TEAM_ID', 'GAME_DATE', 'season']],
                      back[['PLAYER_ID', 'GAME_ID', 'TEAM_ID', 'GAME_DATE', 'season']]]).drop_duplicates(['PLAYER_ID', 'GAME_ID'])
    allr = asof(allr).merge(positions, on='PLAYER_ID', how='left') \
                     .merge(back[['GAME_ID', 'PLAYER_ID', 'back']], on=['GAME_ID', 'PLAYER_ID'], how='left')
    w = allr.set_index(['GAME_ID', 'PLAYER_ID']).index.map(wmap).fillna(0).values
    allr['ret_min'], allr['ret_min_pos'] = returning(allr, allr['mpg'].fillna(0).values, w,
                                                     allr['back'].fillna(False).astype(bool).values, 'pos')
    x = key.merge(allr[['GAME_ID', 'PLAYER_ID', 'pos', 'ret_min', 'ret_min_pos']], on=['GAME_ID', 'PLAYER_ID'], how='left')
    x.loc[x['season'] < REPORT_ERA, RETURNING] = np.nan

    # opponent's absences, weighted as at noon
    hw = asof(half.copy()).merge(positions, on='PLAYER_ID', how='left')
    hw['m'], hw['p'] = hw['mpg'].fillna(0) * hw['weight'], hw['ppg'].fillna(0) * hw['weight']
    ot = hw.groupby(['GAME_ID', 'TEAM_ID']).agg(opp_out_min=('m', 'sum'), opp_out_ppg=('p', 'sum')).reset_index()
    op = hw.groupby(['GAME_ID', 'TEAM_ID', 'pos'])['m'].sum().rename('opp_out_min_pos').reset_index()
    x = x.merge(ot.rename(columns={'TEAM_ID': 'OPP_ID'}), on=['GAME_ID', 'OPP_ID'], how='left') \
         .merge(op.rename(columns={'TEAM_ID': 'OPP_ID'}), on=['GAME_ID', 'OPP_ID', 'pos'], how='left')
    x[OPPONENT] = x[OPPONENT].fillna(0)

    gl = clean_lines(pd.read_parquet(DATA / 'game_lines.parquet'))
    x = x.merge(pd.DataFrame({'GAME_ID': gl['GAME_ID'], 'hs': gl['open_spread'].fillna(gl['home_spread']),
                              'total': gl['open_total'].fillna(gl['total'])}), on='GAME_ID', how='left')
    return line_features(x)[['PLAYER_ID', 'GAME_ID'] + FEATURES]


def tonight_lines(day, schedule, games, replay=False):
    """{TEAM_ID: (home spread, total)} for the day's games: ESPN's current number (at noon), or the stored one
    in replays. Missing games are left out (the models handle a blank)."""
    nick = games.drop_duplicates('TEAM_ID').set_index('TEAM_ID')['teamName']
    home = schedule[schedule['is_home'] == 1]
    if replay:
        if not (DATA / 'game_lines.parquet').exists():          # the cloud has no stored lines
            return {}
        gl = clean_lines(pd.read_parquet(DATA / 'game_lines.parquet')).set_index('GAME_ID')
        out = {}
        for gid, t in zip(home['GAME_ID'], home['TEAM_ID']):
            if gid in gl.index:
                r = gl.loc[gid]
                out[t] = (r['open_spread'] if pd.notna(r['open_spread']) else r['home_spread'],
                          r['open_total'] if pd.notna(r['open_total']) else r['total'])
        return out
    from pull_game_lines import events, lines, nick as short
    by_nick = {short(nick.get(t)): t for t in home['TEAM_ID']}
    out = {}
    for eid, hn, _ in events(day):
        t = by_nick.get(short(hn))
        if t is None:
            continue
        ln = lines(eid)
        total = ln.get('total')
        out[t] = (ln.get('home_spread'), total if total is not None and 180 <= total <= 280 else np.nan)
    missing = len(home) - len(out)
    if missing:
        print(f'warning: no ESPN spread/total for {missing} game(s) today', flush=True)
    return out


def add_tonight(f, games, day, schedule, replay=False):
    """features_as_of rows (every rostered player, out ones included, with out_w, OPP_ID, pos, is_home, GAME_ID)
    -> the context features. Teammates back from a reported absence: missed the team's last game while on that
    game's report (data/noon_injuries.parquet)."""
    from build_features import inferred_absences
    ln = tonight_lines(day, schedule, games, replay)
    home_team = schedule[schedule['is_home'] == 1].set_index('GAME_ID')['TEAM_ID']
    ht = f['GAME_ID'].map(home_team)
    f = f.assign(hs=pd.to_numeric([ln.get(t, (np.nan, np.nan))[0] for t in ht], errors='coerce'),
                 total=pd.to_numeric([ln.get(t, (np.nan, np.nan))[1] for t in ht], errors='coerce'))
    f = line_features(f).drop(columns='hs')

    # returning
    season = f['season'].iloc[0]
    rows = games[(games['season'] == season) & (games['GAME_DATE'] < pd.Timestamp(day))]
    last = rows.drop_duplicates(['TEAM_ID', 'GAME_ID']).sort_values('GAME_DATE').groupby('TEAM_ID')['GAME_ID'].last()
    ab = inferred_absences(rows)
    ab = ab[ab['GAME_ID'].isin(set(last.values))]
    try:
        rep = pd.read_parquet(DATA / 'noon_injuries.parquet', columns=['GAME_ID', 'PLAYER_ID'])
        listed = set(zip(rep['GAME_ID'], rep['PLAYER_ID']))
    except FileNotFoundError:
        listed = set()
    gone = {(p, t) for p, t, gm in zip(ab['PLAYER_ID'], ab['TEAM_ID'], ab['GAME_ID']) if (gm, p) in listed}
    f['back'] = [(p, t) in gone for p, t in zip(f['PLAYER_ID'], f['TEAM_ID'])]
    f['ret_mpg'] = np.where(f['back'] & (f['min_season'] >= RETURN_MPG), f['min_season'], 0.0)
    f['ret_min'], f['ret_min_pos'] = returning(f, f['min_season'].fillna(0).values, f['out_w'].values,
                                               f['back'].values, 'pos')

    # opponent
    m, p = f['min_season'].fillna(0) * f['out_w'], f['pts_season'].fillna(0) * f['out_w']
    tot = pd.DataFrame({'TEAM_ID': f['TEAM_ID'], 'pos': f['pos'], 'm': m, 'p': p})
    team = tot.groupby('TEAM_ID')[['m', 'p']].sum()
    at = tot.groupby(['TEAM_ID', 'pos'])['m'].sum()
    f['opp_out_min'] = f['OPP_ID'].map(team['m']).fillna(0)
    f['opp_out_ppg'] = f['OPP_ID'].map(team['p']).fillna(0)
    f['opp_out_min_pos'] = [at.get((o, ps), 0.0) for o, ps in zip(f['OPP_ID'], f['pos'])]
    return f.drop(columns='back')


if __name__ == '__main__':
    h = history()
    h.to_parquet(PATH, index=False)
    print(f'saved {PATH.name}: {len(h):,} rows |', ' | '.join(f'{c} {h[c].notna().mean():.0%} filled' for c in FEATURES))
