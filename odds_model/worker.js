// The site's Worker: serves the static pages (data/site) to anyone with the private link, and starts the daily
// runs on time (scheduled(), crons in wrangler.jsonc): results at 9:00 AM ET, picks at 12:00 PM ET, a picks rerun as soon
// as the NBA posts the day's injury report if it wasn't out by noon, and a closing-line run whenever a bet is about to tip.
//
// Private link: https://<site>/?k=<VIEW_KEY>. Opening it sets a cookie for 400 days (the browser maximum) and
// redirects to the plain address, so later visits from that browser just work. Without the key or the cookie
// the site shows a short "private" page. Secrets: VIEW_KEY (the link key), GITHUB_TOKEN (a fine-grained token
// limited to Actions on the belch-bets repo, for the cron).
const REPO = 'abeilke2002/belch-bets', WORKFLOW = 'daily.yml';
const COOKIE = 'bb_key', MAX_AGE = 400 * 24 * 3600;

const hasCookie = (request, key) =>
  (request.headers.get('cookie') || '').split(';').some(c => c.trim() === `${COOKIE}=${key}`);

const PRIVATE = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>The Noon Line</title><style>body{background:#0b0d10;color:#b9bfc8;font:15px/1.5 -apple-system,Helvetica,Arial,sans-serif;
display:grid;place-items:center;min-height:100vh;margin:0;padding:0 16px;text-align:center}b{color:#eceef1}</style></head>
<body><p><b>This site is private.</b><br>Open it with the link you were sent.</p></body></html>`;

const CLOSE_LINES = false;           // evening closing-line pulls (see daily_pipeline.run_close)

export default {
  async fetch(request, env) {
    const url = new URL(request.url), key = env.VIEW_KEY;
    if (!key) return new Response('VIEW_KEY is not set on the Worker.', { status: 500 });

    if (url.searchParams.get('k') === key) {               // the private link: remember this browser, then clean the URL
      url.searchParams.delete('k');
      return new Response(null, { status: 302, headers: {
        location: url.pathname + url.search,
        'set-cookie': `${COOKIE}=${key}; Max-Age=${MAX_AGE}; Path=/; Secure; HttpOnly; SameSite=Lax`,
        'cache-control': 'no-store' } });
    }
    if (!hasCookie(request, key))
      return new Response(PRIVATE, { status: 403, headers: { 'content-type': 'text/html; charset=utf-8',
        'cache-control': 'no-store', 'x-robots-tag': 'noindex' } });

    const res = await env.ASSETS.fetch(request);
    const out = new Response(res.body, res);
    out.headers.set('x-robots-tag', 'noindex');
    return out;
  },

  // GitHub's own schedule starts runs hours late; a dispatch starts within a minute. Cron times are UTC, so the daily
  // runs fire at both EDT and EST hours and only the one at the right New York hour dispatches: 9:00 results, 12:00 picks.
  // The evening cron (every 15 min) starts a closing-line run only when a bet without a closing line tips within 20 min.
  async scheduled(controller, env, ctx) {
    const at = new Date(controller.scheduledTime);
    const ny = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric',
      minute: 'numeric', hour12: false }).formatToParts(at).map(p => [p.type, Number(p.value)]));
    let mode = controller.cron.startsWith('0 ') && ny.minute === 0 ? { 9: 'results', 12: 'picks' }[ny.hour] : null, args = '';
    // Closing-line runs are off (free Odds API plan: credits go to the noon pull). Set CLOSE_LINES = true to bring them back.
    if (CLOSE_LINES && !mode && controller.cron.startsWith('*/15')) mode = (await closeDue(env, at)) ? 'close' : null;
    if (!mode && controller.cron.startsWith('*/10') && ny.hour >= 12 && ny.hour < 16 && await lateReport(env, at, ny))
      [mode, args] = ['picks', '--late-report'];
    if (!mode) return;
    const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
      method: 'POST', body: JSON.stringify({ ref: 'main', inputs: { mode, args } }),
      headers: { authorization: `Bearer ${env.GITHUB_TOKEN}`, accept: 'application/vnd.github+json',
                 'x-github-api-version': '2022-11-28', 'user-agent': 'belch-bets-worker' } });
    if (r.status !== 204) throw new Error(`${mode} dispatch: GitHub said ${r.status}`);
  },
};

// Is a bet from today's picks (published picks.json) tipping in the next 20 minutes with no closing line yet?
async function closeDue(env, at) {
  const r = await env.ASSETS.fetch(new Request('https://site.local/picks.json'));
  if (!r.ok) return false;
  const site = await r.json(), ledger = site.record?.ledger || [];
  const closed = new Set(ledger.filter(b => b.date === site.date && b.close != null).map(b => b.player));
  const soon = at.getTime() + 20 * 60 * 1000;
  return (site.picks || []).some(p => !closed.has(p.player) && p.commence_time &&
    Date.parse(p.commence_time) > at.getTime() && Date.parse(p.commence_time) <= soon);
}

// Today's picks ran without a fresh injury report (none since 10 AM by noon): is one up now? At 3 PM, rerun anyway so
// the X post goes out. Report PDFs are named by ET time in 15-minute steps; a missing one answers 403.
async function lateReport(env, at, ny) {
  const r = await env.ASSETS.fetch(new Request('https://site.local/picks.json'));
  if (!r.ok) return false;
  const site = await r.json(), day = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(at);
  if (site.date !== day || !['missing', 'early'].includes(site.slate?.report)) return false;
  if (ny.hour >= 15) return true;
  for (let m = ny.hour * 60 + ny.minute - ny.minute % 15; m >= 12 * 60; m -= 15) {
    const h = Math.floor(m / 60), h12 = String(h % 12 || 12).padStart(2, '0'), mm = String(m % 60).padStart(2, '0');
    const res = await fetch(`https://ak-static.cms.nba.com/referee/injury/Injury-Report_${day}_${h12}_${mm}${h < 12 ? 'AM' : 'PM'}.pdf`,
                            { method: 'HEAD' });
    if (res.ok) return true;
  }
  return false;
}
