// The site's Worker: serves the static pages (data/site) and two small endpoints for the "Update now" button.
//   POST /api/update  starts the picks run on GitHub Actions (workflow_dispatch)
//   GET  /api/status  the latest run's state, so the page can show progress
// Both require Cloudflare Access (the approved-emails login): without it anyone could start runs and spend
// Odds API credits. Secret GITHUB_TOKEN: a fine-grained token limited to Actions on the belch-bets repo.
const REPO = 'abeilke2002/belch-bets', WORKFLOW = 'daily.yml';

const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });

async function gh(env, path, init = {}) {
  return fetch(`https://api.github.com/repos/${REPO}${path}`, { ...init, headers: {
    authorization: `Bearer ${env.GITHUB_TOKEN}`, accept: 'application/vnd.github+json',
    'x-github-api-version': '2022-11-28', 'user-agent': 'belch-bets-worker', ...(init.headers || {}) } });
}

async function latestRun(env) {
  const r = await gh(env, `/actions/workflows/${WORKFLOW}/runs?per_page=1`);
  if (!r.ok) return null;
  const run = (await r.json()).workflow_runs?.[0];
  return run && { id: run.id, status: run.status, conclusion: run.conclusion, started: run.run_started_at,
                  updated: run.updated_at, event: run.event, url: run.html_url };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith('/api/')) return env.ASSETS.fetch(request);

    // Cloudflare Access adds this header to every request it lets through
    if (!request.headers.get('cf-access-jwt-assertion'))
      return json({ ok: false, error: 'The update button only works once the site login (Cloudflare Access) is on.' }, 403);
    if (!env.GITHUB_TOKEN) return json({ ok: false, error: 'GITHUB_TOKEN is not set on the Worker.' }, 500);

    if (url.pathname === '/api/status') return json({ ok: true, run: await latestRun(env) });

    if (url.pathname === '/api/update' && request.method === 'POST') {
      const run = await latestRun(env);
      if (run && run.status !== 'completed')
        return json({ ok: false, error: 'An update is already running.', run }, 409);
      if (run && Date.now() - Date.parse(run.started) < 5 * 60 * 1000)
        return json({ ok: false, error: 'An update finished in the last 5 minutes. Try again shortly.', run }, 429);
      const r = await gh(env, `/actions/workflows/${WORKFLOW}/dispatches`, {
        method: 'POST', body: JSON.stringify({ ref: 'main', inputs: { mode: 'picks' } }) });
      return r.status === 204 ? json({ ok: true }) : json({ ok: false, error: `GitHub said ${r.status}` }, 502);
    }
    return json({ ok: false, error: 'not found' }, 404);
  },
};
