"""Why the model projected what it did: each projection split into drivers (grouped model inputs) that add up to it.

LightGBM gives every prediction as a starting value (the average prediction) plus one contribution per input
(TreeSHAP, exact for trees). Related inputs are grouped into a handful of readable drivers, each shown with the
player's own number for it. The rebounds/assists models predict on a log scale (Poisson); their contributions are
converted to rebounds/assists so the bars still add up to the projection.

    drivers(model, X, 'points', link='identity')  ->  per row: {'base', 'pred', 'drivers': [{label, value, contrib}]}
"""
import numpy as np

fmt = lambda v, f: '' if v is None or (isinstance(v, float) and np.isnan(v)) else f.format(v)


def _role(r):
    s = 'starter' if r.get('started_last', 0) >= 0.5 else 'bench'
    return f"{s}, {r.get('start_rate', 0):.0%} starts"


# (label, inputs, the player's number for it)
GROUPS = {
    'points': [
        ('Projected minutes', ['pred_minutes'], lambda r: fmt(r.get('pred_minutes'), '{:.1f} min')),
        ('Season scoring', ['pts_season', 'fga_season', 'fta_season', 'usage_share'], lambda r: fmt(r.get('pts_season'), '{:.1f} ppg')),
        ('Recent scoring', ['pts_5', 'pts_3', 'fga_5', 'fga_3', 'fta_5'], lambda r: fmt(r.get('pts_5'), 'L5 {:.1f}')),
        ('Last season', ['prev_season_ppg'], lambda r: fmt(r.get('prev_season_ppg'), '{:.1f} ppg')),
        ('Starting role', ['start_rate', 'started_last', 'starts_5'], _role),
        ('Teammates out', ['out_ppg', 'out_min', 'n_out', 'exp_extra_fga_new', 'exp_extra_pts_new', 'exp_extra_pts_recent',
                           'out_min_pos', 'n_active_pos', 'pos_vacancy'], lambda r: fmt(r.get('out_ppg'), '{:.1f} ppg out')),
        ('Teammates back', ['ret_min', 'ret_min_pos'], lambda r: fmt(r.get('ret_min'), '{:.0f} min back')),
        ('Opponent', ['opp_pos_ratio', 'opp_total_ratio', 'opp_out_min', 'opp_out_ppg', 'opp_out_min_pos'],
         lambda r: fmt(r.get('opp_total_ratio'), 'allows {:.2f}x')),
        ('Game spread / total', ['team_spread', 'abs_spread', 'total', 'team_implied'],
         lambda r: f"{fmt(r.get('team_spread'), '{:+.1f}')} / {fmt(r.get('total'), '{:.0f}')}"),
        ('Rest', ['rest_days'], lambda r: fmt(r.get('rest_days'), '{:.0f} days')),
        ('Position', ['pos_code'], lambda r: ''),
    ],
    'minutes': [
        ('Season minutes', ['min_season'], lambda r: fmt(r.get('min_season'), '{:.1f} min')),
        ('Recent minutes', ['min_5', 'min_3'], lambda r: fmt(r.get('min_5'), 'L5 {:.1f}')),
        ('Starting role', ['start_rate', 'started_last', 'starts_5'], _role),
        ('Scoring level', ['pts_season'], lambda r: fmt(r.get('pts_season'), '{:.1f} ppg')),
        ('Back from absence', ['games_missed_before', 'games_since_return', 'last_absence_len'],
         lambda r: fmt(r.get('games_since_return'), '{:.0f} g since return')),
        ('Teammates out', ['out_fga', 'out_fga_share', 'out_min_pos', 'n_active_pos', 'pos_vacancy'],
         lambda r: fmt(r.get('out_min_pos'), '{:.0f} min at pos.')),
        ('Teammates back', ['ret_min', 'ret_min_pos'], lambda r: fmt(r.get('ret_min'), '{:.0f} min back')),
        ('Opponent injuries', ['opp_out_min', 'opp_out_ppg', 'opp_out_min_pos'], lambda r: fmt(r.get('opp_out_ppg'), '{:.1f} ppg out')),
        ('Game spread / total', ['team_spread', 'abs_spread', 'total', 'team_implied'],
         lambda r: f"{fmt(r.get('team_spread'), '{:+.1f}')} / {fmt(r.get('total'), '{:.0f}')}"),
        ('Games played', ['gp'], lambda r: fmt(r.get('gp'), '{:.0f} g')),
        ('Rest', ['rest_days'], lambda r: fmt(r.get('rest_days'), '{:.0f} days')),
        ('Position', ['pos_code'], lambda r: ''),
    ],
}
for stat, s in [('rebounds', 'reb'), ('assists', 'ast')]:
    GROUPS[stat] = [
        ('Projected minutes', ['pred_minutes', 'min_season', 'min_5'], lambda r: fmt(r.get('pred_minutes'), '{:.1f} min')),
        (f'Season {stat}', [f'{s}_season', f'{s}_pm_season', 'oreb_season', 'oreb_share', 'usage_share'],
         lambda r, s=s: fmt(r.get(f'{s}_season'), '{:.1f} / g')),
        (f'Recent {stat}', [f'{s}_10', f'{s}_5', f'{s}_3', f'{s}_pm_10'], lambda r, s=s: fmt(r.get(f'{s}_5'), 'L5 {:.1f}')),
        ('Last season', [f'{s}_prev'], lambda r, s=s: fmt(r.get(f'{s}_prev'), '{:.1f} / g')),
        ('Starting role', ['start_rate', 'started_last'], _role),
        ('Opponent', [f'opp_{s}_allowed', 'opp_misses', 'opp_pace', 'opp_out_min', 'opp_out_ppg', 'opp_out_min_pos'],
         lambda r, s=s: fmt(r.get(f'opp_{s}_allowed'), 'allows {:.1f}')),
        ('Team', ['misses', 'team_reb', 'team_ast', 'pace'], lambda r: fmt(r.get('pace'), 'pace {:.0f}')),
        ('Teammates out', [f'out_{s}', f'out_{s}_pos', f'new_out_{s}', f'new_out_{s}_pos', f'exp_extra_{s}', 'out_min', 'n_out',
                           'out_min_pos', 'pos_vacancy', 'n_active_pos'], lambda r, s=s: fmt(r.get(f'out_{s}'), '{:.1f} out')),
        ('Teammates back', ['ret_min', 'ret_min_pos'], lambda r: fmt(r.get('ret_min'), '{:.0f} min back')),
        ('Game spread / total', ['team_spread', 'abs_spread', 'total', 'team_implied'],
         lambda r: f"{fmt(r.get('team_spread'), '{:+.1f}')} / {fmt(r.get('total'), '{:.0f}')}"),
        ('Rest & games', ['rest_days', 'gp'], lambda r: fmt(r.get('rest_days'), '{:.0f} days rest')),
        ('Position', ['pos_code'], lambda r: ''),
    ]


def drivers(model, X, kind, link='identity', top=8):
    """For each row of X (the exact inputs the model saw): base, prediction and the top drivers (rest as 'Other')."""
    feats = list(X.columns)
    c = model.predict(X, pred_contrib=True)
    raw, bias = c[:, :-1], c[:, -1]
    if link == 'log':                                   # log-scale contributions -> stat units that add up exactly
        S = raw.sum(1)
        mu0 = np.exp(bias)
        scale = np.where(np.abs(S) < 1e-9, mu0, mu0 * np.expm1(S) / np.where(np.abs(S) < 1e-9, 1, S))
        units, base, pred = raw * scale[:, None], mu0, mu0 * np.exp(S)
    else:
        units, base, pred = raw, bias, bias + raw.sum(1)
    groups = GROUPS[kind]
    idx = {f: i for i, f in enumerate(feats)}
    out = []
    for k, (_, r) in enumerate(X.iterrows()):
        rd, used, rows = r.to_dict(), set(), []
        for label, fs, val in groups:
            cols = [idx[f] for f in fs if f in idx]
            if cols:
                used |= set(cols)
                rows.append({'label': label, 'value': val(rd), 'contrib': float(units[k, cols].sum())})
        rest = [i for i in range(len(feats)) if i not in used]
        if rest:
            rows.append({'label': 'Other', 'value': '', 'contrib': float(units[k, rest].sum())})
        rows.sort(key=lambda d: -abs(d['contrib']))
        keep, extra = rows[:top], rows[top:]
        if extra:
            keep.append({'label': 'Everything else', 'value': '', 'contrib': float(sum(d['contrib'] for d in extra))})
        out.append({'base': float(base[k]), 'pred': float(pred[k]), 'drivers': keep})
    return out


# ---------------------------------------------------------------- the whole bet

sig = lambda z: 1 / (1 + np.exp(-z))
lgt = lambda p: np.log(p / (1 - p))


def bet_steps(p_fn, novig_over, side, price, proj, unit):
    """The bet as a chain: sportsbooks' no-vig chance for the side -> + the model's constant lean -> + the projection's
    effect = the model's chance; the break-even at the price; and how much 1 unit of projection moves the chance.
    p_fn(proj) is the model's P(over) at a projection (None = the projection exactly neutral: no gap term)."""
    from parse_odds import american_to_prob
    s = (lambda p: p) if side == 'OVER' else (lambda p: 1 - p)
    mkt, lean, final = s(novig_over), s(p_fn(None)), s(p_fn(proj))
    need = float(np.asarray(american_to_prob(np.array([price])))[0])
    per = s(p_fn(proj + 0.5)) - s(p_fn(proj - 0.5))
    r = lambda v: round(float(v), 4)
    return {'side': side, 'proj': r(proj), 'price': int(price), 'market': r(mkt), 'lean': r(lean - mkt),
            'proj_eff': r(final - lean), 'p': r(final), 'need': r(need), 'per_unit': r(per), 'unit': unit}


def points_p_fn(om, bins, sds, novig_over, line):
    from predict_today import sd_for
    Lm = lgt(novig_over)
    def f(proj):
        if proj is None:
            return sig(Lm + om['b0'])
        gap, sd = proj - line, float(sd_for(bins, sds, np.array([proj]))[0])
        return sig(Lm + om['b0'] + om['b_gap'] * gap + om['b_z'] * gap / sd)
    return f


def stat_p_fn(m, novig_over, line):
    import stat_backtest as SB
    Lm, b = lgt(novig_over), np.asarray(m['clf_b'])
    def f(proj):
        if proj is None:
            return sig(Lm + b[0])
        p, sd = SB.p_over(np.array([max(proj, 0.05)]), np.array([line]), np.array(m['edges']), np.array(m['rs']))
        p, sd = float(np.clip(p[0], 1e-4, 1 - 1e-4)), float(sd[0])
        feats = {'gap': proj - line, 'gapz': (proj - line) / sd, 'dlogit': lgt(p) - Lm}
        return sig(Lm + b[0] + sum(c * feats[k] for c, k in zip(b[1:], m['clf_cols'])))
    return f


def payload(boards, rows_points, pm, minutes_rows, stat_frames, sm, om):
    """{'market:PLAYER_ID': {'line', 'bet', 'proj', 'minutes'}} for every prop on the day's boards.
    boards: {market: board frame}; rows_points: the points model's exact input rows (with PLAYER_ID);
    minutes_rows: the minutes model's input rows; stat_frames: {market: projection frame with the model's inputs}."""
    clean = lambda ds: [{**d, 'contrib': round(d['contrib'], 2)} for d in ds if abs(d['contrib']) >= 0.005]
    pack = lambda e: {'base': round(e['base'], 2), 'pred': round(e['pred'], 2), 'drivers': clean(e['drivers'])}
    mins = dict(zip(minutes_rows['PLAYER_ID'], drivers(pm['minutes_model'], minutes_rows[pm['minutes_features']], 'minutes')))
    out = {}
    for market, b in boards.items():
        b = b.dropna(subset=['early_line', 'early_novig_over', 'pred_points'])
        if market == 'points':
            r = rows_points[rows_points['PLAYER_ID'].isin(b['PLAYER_ID'])]
            proj = dict(zip(r['PLAYER_ID'], drivers(pm['model'], r[pm['features']], 'points')))
        else:
            fr = stat_frames.get(market)
            if fr is None:
                continue
            fr = fr[fr['PLAYER_ID'].isin(b['PLAYER_ID'])].drop_duplicates('PLAYER_ID')
            proj = dict(zip(fr['PLAYER_ID'], drivers(sm[market]['model'], fr[sm[market]['features']], market, link='log')))
        for _, x in b.iterrows():
            pid = int(x['PLAYER_ID'])
            if pid not in proj:
                continue
            line, pv = float(x['early_line']), float(x['pred_points'])
            pf = points_p_fn(om, pm['bins'], pm['sd'], x['early_novig_over'], line) if market == 'points' \
                else stat_p_fn(sm[market], x['early_novig_over'], line)
            bet = bet_steps(pf, float(x['early_novig_over']), x['side'], x['price'], pv, {'points': 'pt', 'rebounds': 'reb', 'assists': 'ast'}[market])
            if abs(bet['p'] - float(x['p_side'])) > 0.002:      # must match the board, or it isn't shown
                continue
            e = pack(proj[pid])
            if abs(pv - e['pred']) >= 0.05:                      # points: the damped injury adjustment
                e['drivers'].append({'label': 'Injury effect, damped', 'value': '', 'contrib': round(pv - e['pred'], 2)})
                e['pred'] = round(pv, 2)
            out[f'{market}:{pid}'] = {'line': line, 'bet': bet, 'proj': e, **({'minutes': pack(mins[pid])} if pid in mins else {})}
    return out
