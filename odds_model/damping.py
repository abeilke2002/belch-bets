"""Concave damping of the injury adjustment.

The points model over-reacts to big absences (extra shots come at lower efficiency), so the final
prediction is   no-injury prediction + a * adj / (1 + c * |adj|),   adj = prediction - no-injury prediction.
(a, c) are fit on leave-one-season-out predictions, never on the season being predicted.
"""
import numpy as np
from scipy.optimize import curve_fit

from build_features import add_redistribution
from regression import fit

OUT_COLS = ['out_ppg', 'out_min', 'out_fga', 'n_out', 'out_fga_share']


def damp(adj, a, c):
    return a * adj / (1 + c * np.abs(adj))


def no_injury(df):
    """Same rows with nobody out tonight (history of past absences unchanged)."""
    cf = df.copy()
    cf[OUT_COLS] = 0
    return add_redistribution(cf)


def predict_pair(min_model, pts_model, min_f, pts_f, rows):
    """(prediction with tonight's absences, prediction with nobody out) for rows."""
    rows, cf = rows.copy(), no_injury(rows)
    rows['pred_minutes'] = min_model.predict(rows[min_f])
    cf['pred_minutes'] = min_model.predict(cf[min_f])
    return pts_model.predict(rows[pts_f]), pts_model.predict(cf[pts_f])


def _fit_models(train, min_f, pts_f):
    train = train.copy()
    train['pred_minutes'] = np.nan
    for t in train['season'].unique():
        if (train['season'] != t).any():
            m = fit(train.loc[train.season != t, min_f], train.loc[train.season != t, 'MINUTES'])
            train.loc[train.season == t, 'pred_minutes'] = m.predict(train.loc[train.season == t, min_f])
    return fit(train[min_f], train['MINUTES']), fit(train[pts_f], train['points'])


def fit_damping(train, min_f, pts_f):
    """(a, c) from leave-one-season-out predictions within `train`."""
    adjs, resids = [], []
    for t in train['season'].unique():
        tr, va = train[train['season'] != t], train[train['season'] == t]
        if tr['season'].nunique() < 2:
            continue
        p, pcf = predict_pair(*_fit_models(tr, min_f, pts_f), min_f, pts_f, va)
        adjs.append(p - pcf)
        resids.append(va['points'].values - pcf)
    adj, resid = np.concatenate(adjs), np.concatenate(resids)
    (a, c), _ = curve_fit(damp, adj, resid, p0=[1.0, 0.05], bounds=([0, 0], [2, 2]))
    return float(a), float(c)
