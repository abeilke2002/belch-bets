/* The projection models, run in the browser.

   A port of the Python prediction path (predict_today.project / with_absences, build_features.add_redistribution,
   damping.predict_pair / damp). The trees come from data/site/model.json, exported from the trained LightGBM
   models by daily_pipeline.export_model; each player's pre-game inputs come from the day's picks.json ("roster").
   test_browser_model.js checks this file reproduces the Python projections. Works in the browser and in Node. */
(function (root) {
  const OUT_COLS = ['out_ppg', 'out_min', 'out_fga', 'n_out', 'out_fga_share'];
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

  // A team's rows with the teammates-out totals rebuilt from {id: weight}; players at weight 1 are not projected
  function withAbsences(team, weights) {
    const w = p => weights[p.id] ?? 0;
    const sum = col => team.reduce((s, p) => s + (isMissing(p.x[col]) ? 0 : p.x[col] * w(p)), 0);
    const tot = { out_ppg: sum('pts_season'), out_min: sum('min_season'), out_fga: sum('fga_season'),
                  n_out: team.reduce((s, p) => s + w(p), 0) };
    return team.filter(p => w(p) < 1).map(p => {
      const r = { ...p.x, ...tot };
      r.out_fga_share = r.out_fga / r.team_fga_pg;
      return { id: p.id, row: addRedistribution(r) };
    });
  }

  // Minutes, then points with tonight's absences and with nobody out; the injury effect is damped (damping.damp)
  function project(M, row) {
    const r = { ...row };
    r.pred_minutes = predict(M.minutes, r);
    const cf = { ...row };
    for (const c of OUT_COLS) cf[c] = 0;
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

  const api = { predict, addRedistribution, withAbsences, project, teamProjections, inflate };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.BBModel = api;
})(typeof self !== 'undefined' ? self : this);
