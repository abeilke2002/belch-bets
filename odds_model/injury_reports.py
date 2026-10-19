"""Turn the noon injury reports into noon-knowable injury information -> data/noon_injuries.parquet.

One row per (game, team, listed player) with the status as known at noon ET:
  source = 'noon report'          the team had filed by noon
           'previous evening'     not filed by noon, but on the previous evening's report
Teams on neither are absent from the table; noon_features() then falls back to the team's
previous-game absences (what you'd assume at noon without a report).
"""
import pandas as pd

from config import DATA
from name_map import norm, roster_match

REPORTS = DATA / 'injury_reports'
OUT_STATUSES = {'Out', 'Doubtful'}


def flip_name(name):
    """'McCullar Jr., Kevin' -> 'Kevin McCullar Jr.'"""
    if not isinstance(name, str) or ',' not in name:
        return name
    last, first = name.split(',', 1)
    return f'{first.strip()} {last.strip()}'


def load_reports():
    rows = []
    for f in sorted(REPORTS.glob('*.csv')):
        date, kind = f.stem.rsplit('_', 1)
        df = pd.read_csv(f)
        df = df[pd.to_datetime(df['Game Date'], format='%m/%d/%Y', errors='coerce') == pd.Timestamp(date)]
        df = df.assign(GAME_DATE=pd.Timestamp(date), kind=kind)
        df['Team'] = df['Team'].ffill()
        rows.append(df)
    rep = pd.concat(rows, ignore_index=True)
    rep['not_submitted'] = rep['Reason'].astype(str).str.contains('NOT YET SUBMITTED')
    return rep


def build():
    rep = load_reports()
    games = pd.read_parquet(DATA / 'player_games.parquet',
                            columns=['GAME_ID', 'GAME_DATE', 'TEAM_ID', 'teamCity', 'teamName', 'PLAYER_ID',
                                     'player_name', 'season'])
    games['team_full'] = games['teamCity'] + ' ' + games['teamName']
    # report team name -> TEAM_ID (full names; "LA Clippers" / "Los Angeles Clippers" both end in the nickname)
    nick = games.drop_duplicates('TEAM_ID').set_index('teamName')['TEAM_ID']
    rep['TEAM_ID'] = rep['Team'].map(lambda t: next((nick[n] for n in nick.index if str(t).endswith(n)), None))

    # Per (date, team): use the noon report if the team filed by noon, else the previous evening's
    filed = rep[~rep['not_submitted']].groupby(['GAME_DATE', 'TEAM_ID', 'kind']).size().unstack(fill_value=0)
    choice = pd.Series('none', index=filed.index)
    if 'prevday' in filed:
        choice[filed['prevday'] > 0] = 'prevday'
    if 'noon' in filed:
        choice[filed['noon'] > 0] = 'noon'
    rep = rep.merge(choice.rename('use').reset_index(), on=['GAME_DATE', 'TEAM_ID'], how='left')
    rep = rep[(rep['kind'] == rep['use']) & ~rep['not_submitted'] & rep['Player Name'].notna()].copy()
    rep['source'] = rep['kind'].map({'noon': 'noon report', 'prevday': 'previous evening'})

    # Player names -> PLAYER_ID within the team's roster that season
    roster = games.drop_duplicates(['TEAM_ID', 'season', 'PLAYER_ID']).copy()
    roster['key'] = roster['player_name'].map(norm)
    season_of = games.drop_duplicates('GAME_DATE').set_index('GAME_DATE')['season']
    rep['season'] = rep['GAME_DATE'].map(season_of)
    rep['key'] = rep['Player Name'].map(flip_name).map(norm)
    by_team = {k: v for k, v in roster.groupby(['TEAM_ID', 'season'])}
    pids = []
    for r in rep.itertuples():
        cand = by_team.get((r.TEAM_ID, r.season))
        if cand is None:
            pids.append(None); continue
        exact = cand[cand['key'] == r.key]
        pids.append(exact['PLAYER_ID'].iloc[0] if len(exact) == 1 else roster_match(r.key, cand))
    rep['PLAYER_ID'] = pids
    print(f"report rows {len(rep):,} | matched to players {rep['PLAYER_ID'].notna().mean():.1%}")
    unmatched = rep[rep['PLAYER_ID'].isna()]['Player Name'].value_counts()
    if len(unmatched):
        print('unmatched report names (top):', unmatched.head(10).to_dict())

    # Attach GAME_ID
    gid = games.drop_duplicates(['GAME_DATE', 'TEAM_ID'])[['GAME_DATE', 'TEAM_ID', 'GAME_ID']]
    rep = rep.merge(gid, on=['GAME_DATE', 'TEAM_ID'], how='inner')
    out = rep.rename(columns={'Current Status': 'status', 'Reason': 'reason'})[
        ['GAME_ID', 'GAME_DATE', 'TEAM_ID', 'PLAYER_ID', 'status', 'reason', 'source']].dropna(subset=['PLAYER_ID'])
    out['PLAYER_ID'] = out['PLAYER_ID'].astype(int)
    out.to_parquet(DATA / 'noon_injuries.parquet', index=False)

    teams = games.drop_duplicates(['GAME_ID', 'TEAM_ID'])
    teams = teams[teams['season'].isin(rep['season'].dropna().unique())]
    cov = teams.merge(out[['GAME_ID', 'TEAM_ID', 'source']].drop_duplicates(['GAME_ID', 'TEAM_ID']),
                      on=['GAME_ID', 'TEAM_ID'], how='left')['source'].fillna('previous-game fallback')
    print('team-games by source of noon info:', cov.value_counts(normalize=True).round(3).to_dict())
    print('statuses:', out['status'].value_counts().to_dict())
    return out


if __name__ == '__main__':
    build()
