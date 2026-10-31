"""Points predictions (and P(over) when lines + a trained classifier exist) for one day's games.

Replaces the retired python_files/predict.py. Features are built exactly like build_features.py,
from games strictly before --date, so live inputs match what the models were trained on.

    python predict_today.py                                  # today's slate (ET)
    python predict_today.py --out "Jayson Tatum" "Joel Embiid" # injured/resting players
    python predict_today.py --date 2025-03-01 --schedule-from-history   # replay a past day

Writes data/predictions_<date>.csv and data/predictions_today.csv (read by the Streamlit page).
"""
import argparse
import datetime as dt
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd

from build_features import (absence_features, add_opponent, add_redistribution, defense_history, finish_position,
                            inferred_absences, load_positions, lookup_defense, position_absences)
from classifier import add_model_features, predict_over
from config import DATA
from name_map import norm
from parse_odds import american_to_prob
from damping import damp, no_injury, predict_pair
from game_context import add_tonight, returning
from regression import sd_for

ET = ZoneInfo('America/New_York')


def season_of(day):
    y = day.year if day.month >= 8 else day.year - 1
    return f'{y}-{(y + 1) % 100:02d}'


def schedule_from_odds_api(day):
    """Fallback when stats.nba.com is down: the Odds API's event list (free), teams matched by nickname.
    GAME_ID is the event id; it only groups tonight's two teams."""
    from odds_api import OddsAPI
    from config import SPORT
    teams = pd.read_parquet(DATA / 'player_games.parquet', columns=['TEAM_ID', 'teamName']).drop_duplicates('TEAM_ID')
    tid = lambda name: next((t for t, n in zip(teams['TEAM_ID'], teams['teamName']) if name.endswith(n)), None)
    ev = [e for e in OddsAPI().get(f'/sports/{SPORT}/events', expected_cost=0) or []
          if pd.Timestamp(e['commence_time']).tz_convert(ET).date() == day]
    return pd.DataFrame({'GAME_ID': [e['id'] for e in ev], 'HOME_TEAM_ID': [tid(e['home_team']) for e in ev],
                         'VISITOR_TEAM_ID': [tid(e['away_team']) for e in ev]}).dropna()


def schedule_from_espn(day):
    """Regular-season games on `day` from ESPN (reachable from cloud servers, unlike stats.nba.com). GAME_IDs
    match pull_box_scores_espn, so tonight's games line up with tomorrow's box scores."""
    import requests
    teams = pd.read_parquet(DATA / 'player_games.parquet', columns=['TEAM_ID', 'teamName']).drop_duplicates('teamName')
    tid = dict(zip(teams['teamName'], teams['TEAM_ID']))
    sb = requests.get('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard',
                      params={'dates': day.strftime('%Y%m%d')}, timeout=30).json()
    code = '2' + season_of(day)[2:4]
    rows = []
    for e in sb.get('events', []):
        if e.get('season', {}).get('type') != 2:
            continue
        side = {c['homeAway']: tid.get(c['team'].get('name') or c['team']['displayName'].split(' ')[-1])
                for c in e['competitions'][0]['competitors']}
        rows.append({'GAME_ID': f"{code}9{e['id']}", 'HOME_TEAM_ID': side.get('home'), 'VISITOR_TEAM_ID': side.get('away')})
    return pd.DataFrame(rows, columns=['GAME_ID', 'HOME_TEAM_ID', 'VISITOR_TEAM_ID']).dropna()


def schedule_from_api(day):
    """Regular-season games on `day`: ESPN first, the Odds API event list if that fails. Cached in data/schedules/."""
    cache = DATA / 'schedules' / f'{day}.csv'
    if cache.exists():
        return pd.read_csv(cache, dtype={'GAME_ID': str})
    try:
        gh = schedule_from_espn(day)
    except Exception as e:
        print(f'ESPN schedule failed ({type(e).__name__}); using the Odds API event list')
        gh = schedule_from_odds_api(day)
    sched = pd.concat([pd.DataFrame({'GAME_ID': gh['GAME_ID'], 'TEAM_ID': gh['HOME_TEAM_ID'], 'is_home': 1}),
                       pd.DataFrame({'GAME_ID': gh['GAME_ID'], 'TEAM_ID': gh['VISITOR_TEAM_ID'], 'is_home': 0})])
    if len(sched):                                  # never cache an empty day (could be a failed lookup)
        cache.parent.mkdir(exist_ok=True)
        sched.to_csv(cache, index=False)
    return sched


def schedule_from_history(games, day):
    return games[games['GAME_DATE'] == pd.Timestamp(day)][['GAME_ID', 'TEAM_ID', 'is_home']].drop_duplicates()


def features_as_of(games, day, schedule, out_names, out_weights=None, keep_out=False):
    """One row per player on a scheduled team, using only games before `day` (same as build_features).

    out_names: players ruled out (weight 1). out_weights: {PLAYER_ID: weight} from the noon report
    (Out/Doubtful 1, Questionable 0.5). Weights scale each absent teammate's averages in the out_* totals,
    as in the backtest; players at weight 1 are dropped, partial ones are still predicted."""
    season = season_of(day)
    hist = games[games['played'] & (games['GAME_DATE'] < pd.Timestamp(day))]
    cur = hist[hist['season'] == season].sort_values(['PLAYER_ID', 'GAME_DATE'])
    if cur.empty:
        raise ValueError(f'No {season} regular-season games before {day} yet, so there is no '
                         f'current-season history to predict from.')

    g = cur.groupby('PLAYER_ID')
    last = g.tail(1).set_index('PLAYER_ID')
    f = pd.DataFrame({'TEAM_ID': last['TEAM_ID'], 'player_name': last['player_name'],
                      'team': last['teamName'],
                      'gp': g.size(), 'last_game': last['GAME_DATE']})
    for col, name in [('points', 'pts'), ('fieldGoalsAttempted', 'fga'),
                      ('freeThrowsAttempted', 'fta'), ('MINUTES', 'min')]:
        f[f'{name}_season'] = g[col].mean()
        for w in (3, 5):
            f[f'{name}_{w}'] = g[col].apply(lambda x: x.tail(w).mean() if len(x) >= w else np.nan)
    f['pts_std'] = g['points'].apply(lambda x: x.std() if len(x) >= 3 else np.nan)
    f['start_rate'] = g['started'].mean()
    f['started_last'] = last['started']
    f['starts_5'] = g['started'].apply(lambda x: x.tail(5).mean() if len(x) >= 5 else np.nan)
    f['rest_days'] = ((pd.Timestamp(day) - f['last_game']).dt.days).clip(upper=10)

    prev = f"{int(season[:4]) - 1}-{int(season[:4]) % 100:02d}"
    f['prev_season_ppg'] = hist[hist['season'] == prev].groupby('PLAYER_ID')['points'].mean()

    # Teammates ruled out (season ppg to date, same definition as build_features)
    out_keys = {norm(n) for n in out_names}
    f['out_w'] = np.where(f['player_name'].map(norm).isin(out_keys), 1.0,
                          f.index.map(lambda p: (out_weights or {}).get(p, 0.0)))
    f['is_out'] = f['out_w'] >= 1
    w = f[f['out_w'] > 0]
    team_out = pd.DataFrame({'out_ppg': w['pts_season'] * w['out_w'], 'out_min': w['min_season'] * w['out_w'],
                             'out_fga': w['fga_season'] * w['out_w'], 'n_out': w['out_w'],
                             'TEAM_ID': w['TEAM_ID']}).groupby('TEAM_ID').sum()
    f = f.reset_index().merge(team_out, on='TEAM_ID', how='left')
    f[['out_ppg', 'out_min', 'out_fga', 'n_out']] = f[['out_ppg', 'out_min', 'out_fga', 'n_out']].fillna(0)
    team_fga = cur.groupby(['TEAM_ID', 'GAME_ID'])['fieldGoalsAttempted'].sum().groupby('TEAM_ID').mean()
    f['team_fga_pg'] = f['TEAM_ID'].map(team_fga)
    f['out_fga_share'] = f['out_fga'] / f['team_fga_pg']
    f['out_fga_season_avg'] = f['PLAYER_ID'].map(g['out_fga'].mean())
    f['out_fga_5'] = f['PLAYER_ID'].map(g['out_fga'].apply(lambda x: x.tail(5).mean()))
    f = add_redistribution(f)
    missing = out_keys - set(f.loc[f['is_out'], 'player_name'].map(norm))
    if missing:
        print(f'warning: --out names not found among this season\'s players: {sorted(missing)}')

    f = f.merge(add_opponent(schedule), on='TEAM_ID')    # keep only teams playing that day
    if f.empty:                                          # early in a season: only other teams have played
        raise ValueError(f'No one playing on {day} has played a {season} game yet, so there is no '
                         f'current-season history to predict from.')
    f = f.merge(load_positions(), on='PLAYER_ID', how='left')
    f = finish_position(f.merge(position_absences(f.assign(mpg=f['min_season'], w=f['out_w'])),
                                on=['GAME_ID', 'TEAM_ID', 'pos'], how='left'))
    f['season'], f['GAME_DATE'] = season, pd.Timestamp(day)
    # Absence features: append tonight's game to the season history and reuse the training code
    tonight = f[['PLAYER_ID', 'TEAM_ID', 'GAME_ID', 'season', 'GAME_DATE']].assign(played=True, cd_dnp=False)
    season_rows = games[(games['season'] == season) & (games['GAME_DATE'] < pd.Timestamp(day))]
    absences = absence_features(pd.concat([season_rows, tonight], ignore_index=True))
    f = f.merge(absences, on=['PLAYER_ID', 'GAME_ID'], how='left')
    f[['opp_pos_ratio', 'opp_total_ratio']] = lookup_defense(
        f[['OPP_ID', 'season', 'pos', 'GAME_DATE']], defense_history(hist))
    # spread/total, teammates back from a reported absence, the opponent's absences (stored lines in replays)
    f = add_tonight(f, games, day, schedule, replay=bool((games['GAME_DATE'] == pd.Timestamp(day)).any()))
    return f.copy() if keep_out else f[~f['is_out']].copy()


def likely_out(games, day, schedule):
    """Players who missed their team's most recent game (incl. long-term injuries), for teams playing on
    `day`. Used to pre-fill the injury list; remove anyone who is returning tonight."""
    season = season_of(day)
    hist = games[(games['season'] == season) & (games['GAME_DATE'] < pd.Timestamp(day))]
    if hist.empty:
        return []
    out = inferred_absences(hist)
    last_game = hist.groupby('TEAM_ID')['GAME_DATE'].max().rename('last_date').reset_index()
    out = out.merge(last_game, on='TEAM_ID')
    out = out[(out['GAME_DATE'] == out['last_date']) & out['TEAM_ID'].isin(schedule['TEAM_ID'])]
    names = hist.drop_duplicates('PLAYER_ID').set_index('PLAYER_ID')['player_name']
    return sorted(names.reindex(out['PLAYER_ID'].unique()).dropna())


def attach_lines(f, day, snap):
    """The day's lines from the live log, else from the historical pull (for replaying past days)."""
    lines = pd.DataFrame()
    for path in [DATA / 'live' / 'odds_lines.parquet', DATA / 'odds_lines.parquet']:
        if path.exists():
            x = pd.read_parquet(path)
            lines = x[pd.to_datetime(x['commence_time'], utc=True).dt.tz_convert(ET).dt.date == day]
            if not lines.empty:
                break
    if lines.empty:
        return f
    lines = lines.dropna(subset=[f'{snap}_line'])
    lines['key'] = lines['player'].map(norm)
    return f.assign(key=f['player_name'].map(norm)).merge(
        lines.drop(columns=['player']), on='key', how='left').drop(columns='key')


def stake_for(edge, gp, avg_edge):
    """Units: edge / average pick edge, in 0.25u steps, 0.25-1.5u; capped at 1u when edge >= 8% (least
    reliable) and 0.5u until the player has 20 games this season."""
    u = (np.round(edge / avg_edge * 4) / 4).clip(0.25, 1.5)
    u = u.where(edge < 0.08, u.clip(upper=1.0))
    return u.where(gp >= 20, u.clip(upper=0.5))


def load_schedule(games, day, from_history=False):
    return schedule_from_history(games, day) if from_history else schedule_from_api(day)


EPS = 1e-9          # inputs this close to 0 are 0 (rounding specks from summing in a different order); site/model.js does the same


def snap(df, cols):
    """Rounding specks -> exactly 0, so Python and the browser model always take the same branch at zero splits."""
    df = df.copy()
    df[cols] = df[cols].mask(df[cols].abs() < EPS, 0.0)
    return df


def project(f, pm):
    """Minutes and points for feature rows (damped injury adjustment, as in training). Same steps as
    damping.predict_pair, with snap() before each model call so site/model.js reproduces it exactly."""
    mf, pf = pm['minutes_features'], pm['features']
    rows, cf = snap(f, mf), snap(no_injury(f), mf)
    rows['pred_minutes'] = pm['minutes_model'].predict(rows[mf])
    cf['pred_minutes'] = pm['minutes_model'].predict(cf[mf])
    rows, cf = snap(rows, pf), snap(cf, pf)
    raw, no_inj = pm['model'].predict(rows[pf]), pm['model'].predict(cf[pf])
    f = f.copy()
    f['pred_minutes'] = rows['pred_minutes'].values
    f['pred_points'] = no_inj + damp(raw - no_inj, *pm['damping'])
    return f


def with_absences(team, weights):
    """One team's rows with the teammates-out totals rebuilt from {PLAYER_ID: weight} (same as features_as_of)."""
    t = team.copy()
    w = t['PLAYER_ID'].map(weights).fillna(0.0)
    t['out_ppg'] = (t['pts_season'] * w).sum()
    t['out_min'] = (t['min_season'] * w).sum()
    t['out_fga'] = (t['fga_season'] * w).sum()
    t['n_out'] = w.sum()
    t['out_fga_share'] = t['out_fga'] / t['team_fga_pg']
    t = add_redistribution(t)
    if 'pos' in t:                                    # position absences rebuilt from the same weights
        t = t.drop(columns=['out_min_pos', 'n_active_pos', 'n_rot_pos', 'pos_vacancy', 'pos_code'], errors='ignore')
        t = finish_position(t.merge(position_absences(t.assign(mpg=t['min_season'], w=w.values)),
                                    on=['GAME_ID', 'TEAM_ID', 'pos'], how='left'))
        t.index = w.index
    if 'ret_mpg' in t:                                # teammates back from an absence, from the same weights
        t['ret_min'], t['ret_min_pos'] = returning(t, t['ret_mpg'].values, w.values, (t['ret_mpg'] > 0).values, 'pos')
    return t[w < 1]                                   # fully-out players aren't projected


def scenarios(games, day, schedule, out_weights, candidates):
    """For each candidate player: every teammate's (points, minutes) with him fully in and fully out, everything
    else as reported. The browser combines these when you change who's playing."""
    pm = joblib.load(DATA / 'models' / 'points_model.pkl')
    fa = features_as_of(games, day, schedule, [], out_weights, keep_out=True)
    out = {}
    for pid in candidates:
        row = fa[fa['PLAYER_ID'] == pid]
        if row.empty:
            continue
        team = fa[fa['TEAM_ID'] == row['TEAM_ID'].iloc[0]]
        res = {}
        for state, w in (('in', 0.0), ('out', 1.0)):
            p = project(with_absences(team, {**(out_weights or {}), pid: w}), pm)
            res[state] = {int(i): [round(float(a), 2), round(float(m), 1)]
                          for i, a, m in zip(p['PLAYER_ID'], p['pred_points'], p['pred_minutes'])}
        out[int(pid)] = res
    return out, fa


def predict_day(games, day, schedule, out_names=(), snapshot='early', margin=0.02, out_weights=None):
    """Points predictions (+ P(over), edge, play when lines and the classifier exist) for one day."""
    f = features_as_of(games, day, schedule, list(out_names), out_weights)
    pm = joblib.load(DATA / 'models' / 'points_model.pkl')
    f = project(f, pm)                                                   # damped injury adjustment
    f['pred_sd'] = sd_for(pm['bins'], pm['sd'], f['pred_points'].values)

    f = attach_lines(f, day, snapshot)
    over_path = DATA / 'models' / 'over_model.pkl'
    if f'{snapshot}_line' in f and f[f'{snapshot}_line'].notna().any() and over_path.exists():
        om = joblib.load(over_path)
        has = f[f'{snapshot}_line'].notna()
        f.loc[has, 'p_over'] = predict_over(om, add_model_features(f[has], snapshot))
        p = f['p_over']
        f['edge_over'] = p - american_to_prob(f[f'{snapshot}_best_over_price'])
        f['edge_under'] = (1 - p) - american_to_prob(f[f'{snapshot}_best_under_price'])
        best = np.where(f['edge_over'] >= f['edge_under'], 'Over', 'Under')
        f['edge'] = np.fmax(f['edge_over'], f['edge_under'])
        f['play'] = np.where(f['edge'] > margin, best, 'No Play')
        f['stake'] = stake_for(f['edge'], f['gp'], om['avg_top_edge']).where(f['play'] != 'No Play')

    keep = ['player_name', 'team', 'TEAM_ID', 'GAME_ID', 'gp', 'pts_season', 'pts_5', 'min_5', 'pred_minutes',
            'pred_points', 'pred_sd', 'out_ppg', 'n_out', 'PLAYER_ID', 'OPP_ID', 'rest_days', 'out_w',
            'event_id', 'commence_time', 'home_team', 'away_team', f'{snapshot}_novig_over', 'close_line', 'close_novig_over',
            f'{snapshot}_line', f'{snapshot}_best_over_price', f'{snapshot}_best_over_book',
            f'{snapshot}_best_under_price', f'{snapshot}_best_under_book', f'{snapshot}_best_over_link',
            f'{snapshot}_best_under_link', 'p_over', 'edge', 'play', 'stake']
    out = f[[c for c in keep if c in f]].sort_values('pred_points', ascending=False)
    out.insert(0, 'date', day.isoformat())
    out.attrs['trained_through'] = pm['trained_through']
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=dt.datetime.now(ET).date().isoformat())
    ap.add_argument('--out', nargs='*', default=[], help='players ruled out tonight')
    ap.add_argument('--snapshot', default='early', choices=['early', 'close'])
    ap.add_argument('--margin', type=float, default=0.02)
    ap.add_argument('--schedule-from-history', action='store_true')
    args = ap.parse_args()
    day = dt.date.fromisoformat(args.date)

    games = pd.read_parquet(DATA / 'player_games.parquet')
    schedule = load_schedule(games, day, args.schedule_from_history)
    if schedule.empty:
        raise SystemExit(f'No games on {day}.')
    out = predict_day(games, day, schedule, args.out, args.snapshot, args.margin)
    out.to_csv(DATA / f'predictions_{day}.csv', index=False)
    out.to_csv(DATA / 'predictions_today.csv', index=False)
    print(out.head(15).round(2).to_string(index=False))
    print(f"\n{len(out)} players | points model trained through {out.attrs['trained_through']} | "
          f"lines: {'yes' if 'p_over' in out else 'none (run daily_logger.py + parse_odds.py)'}")


if __name__ == '__main__':
    main()
