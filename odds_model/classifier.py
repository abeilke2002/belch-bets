"""P(over the noon consensus line): the market's probability, adjusted by how far the projection is from the line.

    z = ln(P_mkt / (1 - P_mkt)) + b0 + b_gap * gap + b_z * gap / sigma        (market weight fixed at 1)
    P_over = 1 / (1 + e^-z)

Only the projection adjustment is learned. Seasons are weighted by recency (each older season counts half as
much as the next), so the model follows the projection's declining value. Trained on noon-knowable
projections (noon injury report, Questionable teammates at half). Chosen in calibration_test.py: its daily
picks were calibrated (predicted 56.1%, won 56.1%) where the previous model was overconfident.

    python classifier.py        # walk-forward report + live model -> data/models/over_model.pkl
"""
import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.metrics import log_loss

from config import DATA, REPORTS
from parse_odds import american_to_decimal, american_to_prob

NOON_PROJECTIONS = DATA / 'noon_projections_half.parquet'
PLAN = [('2024-25', ['2023-24']), ('2025-26', ['2023-24', '2024-25']), ('2023-24', ['2024-25', '2025-26'])]
ON_REPORT = {'Probable', 'Questionable', 'Doubtful'}
MIN_EDGE = 0.02


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1 / (1 + np.exp(-z))


def build_dataset(data_dir):
    """Noon lines matched to players and results, with walk-forward projections (shared by many scripts)."""
    lines = pd.read_parquet(data_dir / 'odds_lines.parquet')
    names = pd.read_parquet(data_dir / 'name_map.parquet')
    games = pd.read_parquet(DATA / 'player_games.parquet')
    preds = pd.read_parquet(DATA / 'regression_preds.parquet')

    df = lines.merge(names, on=['event_id', 'player']).dropna(subset=['PLAYER_ID'])
    df['PLAYER_ID'] = df['PLAYER_ID'].astype(int)
    n_lines = len(df)
    df = df.merge(games.drop(columns=['season']), on=['GAME_ID', 'PLAYER_ID'], how='left')
    df['played'] = df['played'].fillna(False).astype(bool)
    voids = (~df['played']).sum()
    df = df[df['played'] & df['early_line'].notna()]
    df = df.merge(preds.drop(columns=['season']), on=['GAME_ID', 'PLAYER_ID'], how='left')
    pushes = (df['points'] == df['early_line']).sum()
    df = df[df['points'] != df['early_line']].copy()
    print(f'{n_lines:,} matched lines -> {voids:,} voided (DNP/inactive), {pushes:,} pushes dropped, '
          f'{len(df):,} usable')

    df = add_model_features(df)
    df['over'] = (df['points'] > df['line']).astype(int)
    return df.sort_values('GAME_DATE').reset_index(drop=True)


def add_model_features(df, snap='early'):
    """Classifier inputs (logit_novig, gap, gapz) plus market/form columns other scripts use."""
    df = df.copy()
    df['line'] = df[f'{snap}_line']
    df['logit_novig'] = logit(df[f'{snap}_novig_over'])
    df['gap'] = df['pred_points'] - df['line']
    df['gapz'] = df['gap'] / df['pred_sd']
    extras = {'n_books': lambda: df[f'{snap}_n_books'],
              'line_spread': lambda: df[f'{snap}_line_max'] - df[f'{snap}_line_min'],
              'hold': lambda: df[f'{snap}_hold'],
              'season_minus_line': lambda: df['pts_season'] - df['line'],
              'last5_minus_line': lambda: df['pts_5'] - df['line'],
              'min_trend': lambda: df['min_5'] - df['min_season'],
              'pred_min_trend': lambda: df['pred_minutes'] - df['min_season']}
    for col, f in extras.items():
        try:
            df[col] = f()
        except KeyError:
            pass
    return df


def season_weights(seasons):
    """Newest season 1, the one before 0.5, then 0.25, ..."""
    order = sorted(np.unique(np.asarray(seasons)))
    return 0.5 ** pd.Series(seasons).map(lambda s: len(order) - 1 - order.index(s)).values


def fit(train, weighted=True):
    """Learn b0, b_gap, b_z with the market log-odds as a fixed offset (weight 1)."""
    X = train[['gap', 'gapz']].values
    off, y = train['logit_novig'].values, train['over'].values
    w = season_weights(train['season']) if weighted else np.ones(len(train))

    def nll(b):
        p = np.clip(sigmoid(off + b[0] + X @ b[1:]), 1e-6, 1 - 1e-6)
        return -(w * (y * np.log(p) + (1 - y) * np.log(1 - p))).sum() / w.sum()
    b = minimize(nll, np.zeros(3), method='BFGS').x
    return {'b0': float(b[0]), 'b_gap': float(b[1]), 'b_z': float(b[2])}


def predict_over(model, X):
    """P(over) for rows with logit_novig, gap and gapz."""
    return sigmoid(X['logit_novig'].values + model['b0'] + model['b_gap'] * X['gap'].values
                   + model['b_z'] * X['gapz'].values)


def edges(df, p_over):
    """Best side, its edge over the best price's break-even, and the price."""
    eo = p_over - american_to_prob(df['early_best_over_price'])
    eu = (1 - p_over) - american_to_prob(df['early_best_under_price'])
    over = eo >= eu
    return pd.DataFrame({'side_over': over, 'edge': np.maximum(eo, eu), 'p_side': np.where(over, p_over, 1 - p_over),
                         'price': np.where(over, df['early_best_over_price'], df['early_best_under_price'])},
                        index=df.index)


def daily_picks(df):
    """The rule: skip listed players and back-to-backs, one bet a day, the top edge if >= 2%."""
    el = df[~df['status'].isin(ON_REPORT) & (df['rest_days'] != 1)]
    top = el.sort_values('edge', ascending=False).drop_duplicates('GAME_DATE')
    return top[top['edge'] >= MIN_EDGE]


def load_training_data():
    """Noon lines with noon-knowable projections (falls back to the hindsight ones with a warning)."""
    d = build_dataset(DATA)
    if NOON_PROJECTIONS.exists():
        noon = pd.read_parquet(NOON_PROJECTIONS)[['PLAYER_ID', 'GAME_ID', 'pred']]
        d = d.merge(noon, on=['PLAYER_ID', 'GAME_ID']).assign(pred_points=lambda x: x['pred'])
        d = add_model_features(d).drop(columns='pred')
    else:
        print('warning: noon projections not found; training on hindsight projections')
    status = pd.read_parquet(DATA / 'noon_injuries.parquet')[['GAME_ID', 'PLAYER_ID', 'status']] \
        .drop_duplicates(['GAME_ID', 'PLAYER_ID'])
    return d.merge(status, on=['GAME_ID', 'PLAYER_ID'], how='left')


def to_md(df):
    cols = [str(c) for c in df.columns]
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    return '\n'.join(out + ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.itertuples(index=False)])


def main():
    argparse.ArgumentParser().parse_args()
    d = load_training_data()

    rows, picks = [], []
    for test, train in PLAN:
        tr, te = d[d['season'].isin(train)], d[d['season'] == test].copy()
        m = fit(tr)
        te['p_over'] = predict_over(m, te)
        te = te.join(edges(te, te['p_over']))
        b = daily_picks(te)
        picks.append(b)
        rows.append({'test season': test, 'trained on': ' + '.join(train), 'projection weight': round(m['b_z'], 3),
                     'log loss: market / model': f"{log_loss(te['over'], te['early_novig_over']):.4f} / "
                                                 f"{log_loss(te['over'], te['p_over']):.4f}",
                     'daily picks': len(b)})
    b = pd.concat(picks)
    b['win'] = np.where(b['side_over'], b['points'] > b['line'], b['points'] < b['line'])
    avg_edge = b['edge'].mean()
    stake = np.clip(np.round(b['edge'] / avg_edge * 4) / 4, 0.25, 1.5)
    units = np.where(b['win'], american_to_decimal(b['price']) - 1, -1.0) * stake
    summary = (f"Daily picks: {len(b)} bets, predicted {b['p_side'].mean():.1%}, won {b['win'].mean():.1%}, "
               f"{units.sum():+.1f} units with edge-sized stakes")

    # Live model: every season, recency-weighted
    live = fit(d)
    d = d.join(edges(d, predict_over(live, d)), rsuffix='_live')
    top = daily_picks(d)            # live model's own picks set the stake scale (avg stake ~1u)
    seasons = sorted(d['season'].unique())
    live.update({'trained_through': str(d['GAME_DATE'].max().date()),
                 'season_weights': dict(zip(seasons, map(float, season_weights(seasons)))),
                 'avg_top_edge': float(top['edge'].mean()), 'bet_day_share': len(top) / d['GAME_DATE'].nunique(),
                 'min_edge': MIN_EDGE})
    (DATA / 'models').mkdir(exist_ok=True)
    joblib.dump(live, DATA / 'models' / 'over_model.pkl')

    md = ['# Classifier (market fixed, recency-weighted)\n', to_md(pd.DataFrame(rows)), '', summary, '',
          f"Live model: z = market log-odds {live['b0']:+.4f} {live['b_gap']:+.4f} x gap {live['b_z']:+.4f} x gap/sigma; "
          f"stake scale 1u = {live['avg_top_edge']:.2%} edge; a bet on {live['bet_day_share']:.0%} of days", '']
    (REPORTS / 'classifier.md').write_text('\n'.join(md))
    print('\n'.join(md))


if __name__ == '__main__':
    main()
