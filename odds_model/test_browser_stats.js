// Parity check: site/model.js must reproduce the Python rebounds/assists projections and P(over).
//   node test_browser_stats.js <dir with model.json, stat_model.json, day.json (roster), expected.json>
const fs = require('fs'), path = require('path');
const BB = require('./site/model.js');
const dir = process.argv[2], read = f => JSON.parse(fs.readFileSync(path.join(dir, f)));
const M = read('model.json'), S = read('stat_model.json'), D = read('day.json'), exp = read('expected.json');
const teams = BB.inflateStats(S, BB.inflate(M, D.roster));
const got = {};
for (const team of Object.values(teams)) {
  const w = Object.fromEntries(team.map(p => [p.id, p.w]));
  const st = BB.statTeamProjections(S, team, w, BB.teamProjections(M, team, w));
  for (const [m, v] of Object.entries(st)) Object.assign((got[m] ??= {}), v);
}
let ok = true;
for (const [m, e] of Object.entries(exp.proj)) {
  let worst = 0, missing = 0, n = 0;
  for (const [id, v] of Object.entries(e)) {
    const g = got[m]?.[id];
    if (g === undefined) { missing++; continue; }
    n++; worst = Math.max(worst, Math.abs(g - v));
  }
  let pw = 0;
  for (const [id, line, mkt, p] of exp.props[m] || []) {
    const g = got[m]?.[id];
    if (g === undefined) { missing++; continue; }
    pw = Math.max(pw, Math.abs(BB.statScore(S.markets[m], g, line, mkt, -110, -110).pOver - p));
  }
  console.log(`${m}: ${n} players, ${(exp.props[m] || []).length} props, ${missing} missing | max projection diff ${worst.toExponential(2)} | max P(over) diff ${pw.toExponential(2)}`);
  if (!(worst < 0.01 && pw < 0.002 && missing === 0)) ok = false;
}
process.exit(ok ? 0 : 1);
