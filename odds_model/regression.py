"""Two-stage walk-forward model: minutes, then points -> data/regression_preds.parquet.

For each test season S, both models are trained only on seasons before S. Training rows get
predicted minutes from leave-one-season-out models (never their own season), so the points model
learns from minutes predictions as noisy as the ones it sees at test time.

The points features used are the groups kept by feature_study.py (data/selected_features.json);
without that file, every candidate group is used.
"""
import json

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from config import DATA

MINUTES_GROUPS = {
    'minutes averages': ['min_season', 'min_5', 'min_3'],
    'starter role': ['start_rate', 'started_last', 'starts_5'],
    'teammates out': ['out_min', 'out_ppg', 'n_out'],
    'games played': ['gp'],
    'rest': ['rest_days'],
    'home': ['is_home'],
    'scoring level': ['pts_season'],
    'opponent': ['opp_total_ratio'],
    'return from absence': ['games_missed_before', 'games_since_return', 'last_absence_len'],
    'usage freed up': ['out_fga', 'out_fga_share'],
}
POINTS_GROUPS = {
    'season averages': ['pts_season', 'fga_season', 'fta_season'],
    'recent form': ['pts_5', 'pts_3', 'fga_5', 'fga_3', 'fta_5'],
    'raw minutes averages': ['min_season', 'min_5', 'min_3'],
    'predicted minutes': ['pred_minutes'],
    'starter role': ['start_rate', 'started_last', 'starts_5'],
    'volatility': ['pts_std'],
    'games played': ['gp'],
    'rest': ['rest_days'],
    'previous season': ['prev_season_ppg'],
    'teammates out': ['out_ppg', 'out_min', 'n_out'],
    'home': ['is_home'],
    'opponent defense': ['opp_pos_ratio', 'opp_total_ratio'],
    'return from absence': ['games_missed_before', 'games_since_return', 'last_absence_len'],
    'usage freed up': ['out_fga', 'out_fga_share'],
    'shot redistribution (new absences)': ['usage_share', 'exp_extra_fga_new', 'exp_extra_pts_new',
                                           'exp_extra_pts_recent'],
}
TEST_SEASONS = ['2023-24', '2024-25', '2025-26']
PARAMS = dict(n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=200,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)
SELECTED = DATA / 'selected_features.json'


def selected(kind):
    """Features kept by feature_study.py for 'minutes' or 'points' (all candidates if not run yet)."""
    if SELECTED.exists():
        return json.loads(SELECTED.read_text())[kind]
    groups = MINUTES_GROUPS if kind == 'minutes' else POINTS_GROUPS
    return [f for fs in groups.values() for f in fs]


# More teammates out can only raise a player's minutes/points, never lower them (keeps injury toggles
# intuitive at extreme values, where unconstrained trees can wobble). Applied wherever these features appear.
MONOTONE = {'out_fga': 1, 'out_fga_share': 1, 'exp_extra_fga_new': 1, 'exp_extra_pts_new': 1,
            'exp_extra_pts_recent': 1}


def fit(X, y):
    params = dict(PARAMS)
    if any(c in MONOTONE for c in X.columns):
        params['monotone_constraints'] = [MONOTONE.get(c, 0) for c in X.columns]
    return lgb.LGBMRegressor(**params).fit(X, y)


def load_rows():
    df = pd.read_parquet(DATA / 'player_games.parquet')
    ctx = DATA / 'game_context.parquet'                 # spread/total, teammates returning, opponent absences
    if ctx.exists():
        df = df.drop(columns=[c for c in pd.read_parquet(ctx).columns if c not in ('PLAYER_ID', 'GAME_ID')], errors='ignore') \
               .merge(pd.read_parquet(ctx), on=['PLAYER_ID', 'GAME_ID'], how='left')
    return df[df['played'] & (df['gp'] >= 1)].reset_index(drop=True)


def minutes_for_season(df, s, features=None):
    """Predicted minutes for training rows (season < s, leave-one-season-out) and test rows (season s)."""
    features = features or selected('minutes')
    train = df['season'] < s
    pred = pd.Series(np.nan, index=df.index)
    for t in df.loc[train, 'season'].unique():
        fit_rows = train & (df['season'] != t)
        if not fit_rows.any():
            continue
        m = fit(df.loc[fit_rows, features], df.loc[fit_rows, 'MINUTES'])
        pred[df['season'] == t] = m.predict(df.loc[df['season'] == t, features])
    test = df['season'] == s
    if test.any():
        pred[test] = fit(df.loc[train, features], df.loc[train, 'MINUTES']).predict(
            df.loc[test, features])
    return pred


def residual_sd_table(train, features):
    """Out-of-fold residual sd by prediction decile (groups = game dates, so no same-day leakage)."""
    oof = np.zeros(len(train))
    for tr, va in GroupKFold(5).split(train, groups=train['GAME_DATE']):
        oof[va] = fit(train[features].iloc[tr], train['points'].iloc[tr]).predict(train[features].iloc[va])
    bins = np.unique(np.quantile(oof, np.linspace(0, 1, 11)))
    idx = np.clip(np.digitize(oof, bins[1:-1]), 0, len(bins) - 2)
    return bins, pd.Series(train['points'].values - oof).groupby(idx).std()


def sd_for(bins, sd, pred):
    idx = np.clip(np.digitize(pred, bins[1:-1]), 0, len(bins) - 2)
    return sd.reindex(idx).values


def predict_with_sd(model, bins, sd, X, features):
    pred = model.predict(X[features])
    return pred, sd_for(bins, sd, pred)


def main():
    df = load_rows()
    features = selected('points')
    seasons = sorted(df['season'].unique())
    print(f'points features ({len(features)}): {features}')

    preds, rows = [], []
    for s in [s for s in TEST_SEASONS if s in seasons]:
        df['pred_minutes'] = minutes_for_season(df, s)
        train, test = df[(df['season'] < s) & df['pred_minutes'].notna()], df[df['season'] == s].copy()
        from damping import damp, fit_damping, predict_pair
        min_f = selected('minutes')
        min_model, model = fit(train[min_f], train['MINUTES']), fit(train[features], train['points'])
        bins, sd = residual_sd_table(train, features)
        raw, no_inj = predict_pair(min_model, model, min_f, features, test)
        a, c = fit_damping(df[df['season'] < s], min_f, features)       # training seasons only
        test['pred_points_raw'] = raw
        test['pred_points'] = no_inj + damp(raw - no_inj, a, c)
        test['pred_sd'] = sd_for(bins, sd, test['pred_points'].values)
        preds.append(test[['PLAYER_ID', 'GAME_ID', 'season', 'pred_minutes', 'pred_points_raw', 'pred_points', 'pred_sd']])

        for label, m in [('all games', test['gp'] >= 1), ('gp >= 7', test['gp'] >= 7)]:
            t = test[m]
            rmse = lambda p, y='points': np.sqrt(((p - t[y]) ** 2).mean())
            rows.append({'test season': s, 'subset': label, 'n': len(t),
                         'RMSE points': rmse(t['pred_points']), 'RMSE season avg': rmse(t['pts_season']),
                         'RMSE minutes': rmse(t['pred_minutes'], 'MINUTES'),
                         'RMSE minutes (last-5 avg)': rmse(t['min_5'].fillna(t['min_season']), 'MINUTES'),
                         'RMSE undamped': rmse(t['pred_points_raw']),
                         'bias points': (t['pred_points'] - t['points']).mean()})
        print(f'{s}: trained on {len(train):,} rows from {sorted(train.season.unique())}; '
              f'injury damping a={a:.3f}, c={c:.3f}', flush=True)

    pd.concat(preds, ignore_index=True).to_parquet(DATA / 'regression_preds.parquet', index=False)
    print(pd.DataFrame(rows).round(3).to_string(index=False))

    # Final models on every season, for live predictions (predict_today.py)
    min_model = fit(df[selected('minutes')], df['MINUTES'])
    df['pred_minutes'] = minutes_for_season(df, '9999')        # leave-one-season-out on all seasons
    final = fit(df[features], df['points'])
    bins, sd = residual_sd_table(df, features)
    from damping import fit_damping
    a, c = fit_damping(df, selected('minutes'), features)
    print(f'final injury damping: a={a:.3f}, c={c:.3f}')
    (DATA / 'models').mkdir(exist_ok=True)
    joblib.dump({'minutes_model': min_model, 'minutes_features': selected('minutes'), 'model': final,
                 'bins': bins, 'sd': sd, 'features': features, 'damping': (a, c),
                 'trained_through': str(df['GAME_DATE'].max().date())}, DATA / 'models' / 'points_model.pkl')
    print(f"saved models/points_model.pkl (trained through {df['GAME_DATE'].max().date()})")


if __name__ == '__main__':
    main()
