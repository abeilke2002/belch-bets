// The site's Worker: serves the static pages (data/site) to anyone with the private link, and starts the daily
// runs on time (scheduled(), crons in wrangler.jsonc): results at 9:00 AM ET, picks at 12:15 PM ET.
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

  // GitHub's own schedule starts runs hours late; a dispatch starts within a minute. Cron times are UTC, so each run
  // has two crons (EDT and EST) and only the one at the right New York hour dispatches: 9 -> results, 12 -> picks.
  async scheduled(controller, env, ctx) {
    const hour = Number(new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', hour12: false })
      .format(new Date(controller.scheduledTime)));
    const mode = { 9: 'results', 12: 'picks' }[hour];
    if (!mode) return;
    const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
      method: 'POST', body: JSON.stringify({ ref: 'main', inputs: { mode } }),
      headers: { authorization: `Bearer ${env.GITHUB_TOKEN}`, accept: 'application/vnd.github+json',
                 'x-github-api-version': '2022-11-28', 'user-agent': 'belch-bets-worker' } });
    if (r.status !== 204) throw new Error(`${mode} dispatch: GitHub said ${r.status}`);
  },
};
