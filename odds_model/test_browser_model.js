// Parity check: site/model.js must reproduce the Python projections.
//   node test_browser_model.js <site dir> <python projections json>
const fs = require('fs'), path = require('path');
const BB = require('./site/model.js');
const [site, expectedFile] = process.argv.slice(2);
const M = JSON.parse(fs.readFileSync(path.join(site, 'model.json')));
const expected = JSON.parse(fs.readFileSync(expectedFile));
let worst = 0, worstMin = 0, n = 0, missing = 0;
for (const [day, exp] of Object.entries(expected)) {
  const D = JSON.parse(fs.readFileSync(path.join(site, 'history', day + '.json')));
  const teams = BB.inflate(M, D.roster);
  const got = {};
  for (const team of Object.values(teams)) {
    const w = Object.fromEntries(team.map(p => [p.id, p.w]));
    Object.assign(got, BB.teamProjections(M, team, w));
  }
  let dayWorst = 0;
  for (const [id, [pts, mins]] of Object.entries(exp)) {
    const g = got[id];
    if (!g) { missing++; continue; }
    n++;
    dayWorst = Math.max(dayWorst, Math.abs(g.points - pts));
    worstMin = Math.max(worstMin, Math.abs(g.minutes - mins));
  }
  worst = Math.max(worst, dayWorst);
  console.log(`${day}: ${Object.keys(exp).length} players, max points difference ${dayWorst.toExponential(2)}`);
}
console.log(`all: ${n} compared, ${missing} missing | max points diff ${worst.toExponential(2)} | max minutes diff ${worstMin.toExponential(2)}`);
process.exit(worst < 0.01 && worstMin < 0.01 && missing === 0 ? 0 : 1);
