/* The projection models, run in the browser.

   A port of the Python prediction path (predict_today.project / with_absences, build_features.add_redistribution,
   damping.predict_pair / damp). The trees come from data/site/model.json, exported from the trained LightGBM
   models by daily_pipeline.export_model; each player's pre-game inputs come from the day's picks.json ("roster").
   test_browser_model.js checks this file reproduces the Python projections. Works in the browser and in Node. */
(function (root) {
  const OUT_COLS = ['out_ppg', 'out_min', 'out_fga', 'n_out', 'out_fga_share'];
  const ROTATION_MPG = 5;                     // build_features.ROTATION_MPG
  const isMissing = v => v === null || v === undefined || Number.isNaN(v);

  // One tree: node = [feature, threshold, defaultLeft, missingIsNaN, left, right] or a leaf value.
  // Same rule as LightGBM's NumericalDecision: a missing value goes the default way on NaN-type splits,
  // and is treated as 0 on the others.
  function leaf(node, x) {
    while (Array.isArray(node)) {
      let v = x[node[0]];
      if (isMissing(v)) {
        if (node[3]) { node = node[2] ? node[4] : node[5]; continue; }
        v = 0;
      }
      node = v <= node[1] ? node[4] : node[5];
    }
    return node;
  }

  // Inputs within 1e-9 of 0 are 0: rounding specks from summing in a different order would otherwise flip
  // splits that sit at zero (predict_today.snap does the same on the Python side)
  const EPS = 1e-9;
  function predict(m, row) {
    const x = m.features.map(f => { const v = row[f]; return typeof v === 'number' && Math.abs(v) < EPS ? 0 : v; });
    let s = 0;
    for (const t of m.trees) s += leaf(t, x);
    return s;
  }

  // Shots freed by absent teammates, split by each remaining player's usual share (build_features.add_redistribution)
  function addRedistribution(r) {
    const tf = r.team_fga_pg;
    const remaining = Math.max(tf - r.out_fga, 0.5 * tf);
    r.usage_share = r.fga_season / tf;
    const ppf = r.fga_season > 0 ? r.pts_season / r.fga_season : NaN;
    for (const [src, name] of [['out_fga_season_avg', 'new'], ['out_fga_5', 'recent']]) {
      const prior = isMissing(r[src]) ? 0 : r[src];
      const fga = (r.out_fga - prior) * r.fga_season / remaining;
      r['exp_extra_fga_' + name] = fga;
      r['exp_extra_pts_' + name] = fga * ppf;
    }
    return r;
  }

  // Minutes missing at each position and the rotation players left to play them (build_features.position_absences
  // and finish_position): {pos_code: {out, act, rot}}
  function positionAbsences(team, w) {
    const by = {};
    for (const p of team) {
      const pos = p.x.pos_code;
      if (isMissing(pos)) continue;
      const m = isMissing(p.x.min_season) ? 0 : p.x.min_season, rot = p.x.min_season >= ROTATION_MPG ? 1 : 0;
      const g = (by[pos] ??= { out: 0, act: 0, rot: 0 });
      g.out += m * w(p); g.act += rot * (1 - w(p)); g.rot += rot;
    }
    return by;
  }

  // Teammates back from a reported absence (game_context.returning): each one's minutes x (1 - weight), for the team
  // and at the player's position, never counting the player himself. ret_mpg is 0 for everyone else.
  function returning(team, w) {
    const r = p => (isMissing(p.x.ret_mpg) ? 0 : p.x.ret_mpg) * (1 - w(p));
    const tot = team.reduce((s, p) => s + r(p), 0), byPos = {};
    for (const p of team) if (!isMissing(p.x.pos_code)) byPos[p.x.pos_code] = (byPos[p.x.pos_code] || 0) + r(p);
    return p => [Math.max(0, tot - r(p)), isMissing(p.x.pos_code) ? 0 : Math.max(0, byPos[p.x.pos_code] - r(p))];
  }

  // A team's rows with the teammates-out totals rebuilt from {id: weight}; players at weight 1 are not projected.
  // The opponent's absences stay as reported (opp_out_*).
  function withAbsences(team, weights) {
    const w = p => weights[p.id] ?? 0;
    const sum = col => team.reduce((s, p) => s + (isMissing(p.x[col]) ? 0 : p.x[col] * w(p)), 0);
    const tot = { out_ppg: sum('pts_season'), out_min: sum('min_season'), out_fga: sum('fga_season'),
                  n_out: team.reduce((s, p) => s + w(p), 0) };
    const byPos = positionAbsences(team, w), ret = returning(team, w);
    return team.filter(p => w(p) < 1).map(p => {
      const r = { ...p.x, ...tot };
      r.out_fga_share = r.out_fga / r.team_fga_pg;
      const g = isMissing(p.x.pos_code) ? null : byPos[p.x.pos_code];
      r.out_min_pos = g ? g.out : 0;
      r.n_active_pos = Math.max(1, g ? g.act : 1);
      r.n_rot_pos = Math.max(1, g ? g.rot : 1);
      r.pos_vacancy = r.out_min_pos / r.n_active_pos;
      if (!isMissing(p.x.ret_mpg)) [r.ret_min, r.ret_min_pos] = ret(p);
      return { id: p.id, row: addRedistribution(r) };
    });
  }

  // Minutes, then points with tonight's absences and with nobody out; the injury effect is damped (damping.damp)
  function project(M, row) {
    const r = { ...row };
    r.pred_minutes = predict(M.minutes, r);
    const cf = { ...row };
    for (const c of OUT_COLS) cf[c] = 0;
    if (!isMissing(cf.n_rot_pos)) { cf.out_min_pos = 0; cf.pos_vacancy = 0; cf.n_active_pos = cf.n_rot_pos; }  // damping.no_injury
    addRedistribution(cf);
    cf.pred_minutes = predict(M.minutes, cf);
    const raw = predict(M.points, r), noInj = predict(M.points, cf);
    const adj = raw - noInj, [a, c] = M.damping;
    return { minutes: r.pred_minutes, points: noInj + a * adj / (1 + c * Math.abs(adj)) };
  }

  // Every projected player on a team for a given set of weights: {id: {points, minutes}}
  function teamProjections(M, team, weights) {
    const out = {};
    for (const { id, row } of withAbsences(team, weights)) out[id] = project(M, row);
    return out;
  }

  // Roster rows arrive as arrays in M.columns order; turn them into named inputs once
  function inflate(M, roster) {
    const teams = {};
    for (const [abbr, players] of Object.entries(roster))
      teams[abbr] = players.map(p => ({ ...p, x: Object.fromEntries(M.columns.map((c, i) => [c, p.f[i] === null ? NaN : p.f[i]])) }));
    return teams;
  }

  /* ---------- rebounds and assists (stat_models.py; trees from stat_model.json, inputs in each roster row's "s") ---------- */

  // Teammates out tonight, rebuilt from {id: weight} the way stat_backtest.attach_out / add_new_absence build them:
  // what the absent players average (reb_out_avg, ast_out_avg) for the team and at the player's position, how much of it
  // is new compared with his earlier games, and his usual share of it. Minutes come from teamProjections (pts).
  function statRows(S, team, weights, pts) {
    const w = p => weights[p.id] ?? 0, val = (r, c) => isMissing(r[c]) ? 0 : r[c];
    const tot = { reb: 0, ast: 0 }, byPos = {};
    let outMin = 0, nOut = 0;
    for (const p of team) {
      outMin += (isMissing(p.x.min_season) ? 0 : p.x.min_season) * w(p); nOut += w(p);
      if (!p.sx) continue;
      for (const k of ['reb', 'ast']) {
        const v = val(p.sx, k + '_out_avg') * w(p);
        tot[k] += v;
        if (p.spos) { const g = (byPos[p.spos] ??= { reb: 0, ast: 0 }); g[k] += v; }
      }
    }
    // position absences and teammates returning: the same rows the minutes and points models get
    const base = Object.fromEntries(withAbsences(team, weights).map(o => [o.id, o.row]));
    const rows = [];
    for (const p of team) {
      if (w(p) >= 1 || !p.sx || !pts[p.id]) continue;
      const b = base[p.id] || {};
      const r = { ...p.sx, pred_minutes: pts[p.id].minutes, out_min: outMin, n_out: nOut,
                  out_min_pos: b.out_min_pos, n_active_pos: b.n_active_pos, pos_vacancy: b.pos_vacancy,
                  ret_min: b.ret_min, ret_min_pos: b.ret_min_pos };
      for (const k of ['reb', 'ast']) {
        r['out_' + k] = tot[k];
        r['out_' + k + '_pos'] = p.spos && byPos[p.spos] ? byPos[p.spos][k] : 0;
        r['new_out_' + k] = r['out_' + k] - val(p.sx, `out_${k}_usual`);
        r['new_out_' + k + '_pos'] = r['out_' + k + '_pos'] - val(p.sx, `out_${k}_pos_usual`);
        const team_ = p.sx['team_' + k], share = !isMissing(team_) && team_ > 0 ? p.sx[k + '_season'] / team_ : NaN;
        r['exp_extra_' + k] = r['new_out_' + k] * (isMissing(share) ? NaN : share);
      }
      rows.push({ id: p.id, row: r });
    }
    return rows;
  }

  // Poisson LightGBM: the trees sum to the log of the expected count (floored at 0.05, as stat_models.project_tonight)
  const statMean = (m, row) => Math.max(Math.exp(predict(m, row)), 0.05);

  // {market: {id: expected count}} for a team, given its points/minutes projections for the same weights
  function statTeamProjections(S, team, weights, pts) {
    const out = {};
    for (const [market, m] of Object.entries(S.markets)) {
      out[market] = {};
      for (const { id, row } of statRows(S, team, weights, pts)) out[market][id] = statMean(m, row);
    }
    return out;
  }

  // Negative binomial P(count > line) and sd, size r by projection bin (stat_backtest.p_over)
  function nbOver(mu, line, edges, rs) {
    let i = 0;
    while (i < edges.length - 2 && mu >= edges[i + 1]) i++;
    const r = rs[Math.min(i, rs.length - 1)], q = mu / (r + mu), k = Math.floor(line);
    let pmf = Math.pow(r / (r + mu), r), cdf = pmf;
    for (let j = 0; j < k; j++) { pmf *= (j + r) / (j + 1) * q; cdf += pmf; }
    return { p: Math.max(0, 1 - cdf), sd: Math.sqrt(mu + mu * mu / r) };
  }

  const logit = p => Math.log(p / (1 - p)), sigmoid = z => 1 / (1 + Math.exp(-z));
  const implied = a => a > 0 ? 100 / (a + 100) : -a / (-a + 100);

  // P(over) for one prop: the market's no-vig log-odds plus the model's weights (stat_models.score_props), and the
  // edge on each side at the best prices. A side the market doesn't bet (rebound overs) gets edge -1.
  function statScore(m, mu, line, mkt, overPrice, underPrice) {
    const nb = nbOver(mu, line, m.edges, m.rs), pnb = Math.min(Math.max(nb.p, 1e-4), 1 - 1e-4), ln = logit(mkt);
    const f = { gap: mu - line, gapz: (mu - line) / nb.sd, dlogit: logit(pnb) - ln };
    const pOver = sigmoid(ln + m.clf_b[0] + m.clf_cols.reduce((s, c, i) => s + m.clf_b[i + 1] * f[c], 0));
    return { pOver, sd: nb.sd, eo: m.sides.includes('OVER') ? pOver - implied(overPrice) : -1,
             eu: m.sides.includes('UNDER') ? (1 - pOver) - implied(underPrice) : -1 };
  }

  // Attach each roster player's stat inputs (named) once
  function inflateStats(S, teams) {
    for (const players of Object.values(teams))
      for (const p of players) if (p.s) p.sx = Object.fromEntries(S.columns.map((c, i) => [c, p.s[i] === null ? NaN : p.s[i]]));
    return teams;
  }

  const api = { predict, addRedistribution, positionAbsences, withAbsences, project, teamProjections, inflate,
                statRows, statTeamProjections, nbOver, statScore, inflateStats };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.BBModel = api;
})(typeof self !== 'undefined' ? self : this);
