// The site's Worker: serves the static pages (data/site) and two small endpoints for the "Update now" button.
//   POST /api/update  starts the picks run on GitHub Actions (workflow_dispatch)
//   GET  /api/status  the latest run's state, so the page can show progress
//   GET  /api/me      who is logged in and whether they're an owner (the page hides the button otherwise)
// Updates are owner-only (vars.OWNERS in wrangler.jsonc). All of it requires Cloudflare Access (the approved-emails login): without it anyone could start runs and spend
// Odds API credits. Secret GITHUB_TOKEN: a fine-grained token limited to Actions on the belch-bets repo.
const REPO = 'abeilke2002/belch-bets', WORKFLOW = 'daily.yml';

// Who is logged in: verify Cloudflare Access's signed token (cf-access-jwt-assertion) against the team's
// public keys and this application's audience tag, then read the email from it. Plain headers can't fake this.
let CERTS = null;
const b64 = x => Uint8Array.from(atob(x.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - x.length % 4) % 4)),
                                 c => c.charCodeAt(0));
async function accessEmail(request, env) {
  const jwt = request.headers.get('cf-access-jwt-assertion');
  if (!jwt || !env.ACCESS_TEAM || !env.ACCESS_AUD) return null;
  const [h, p, sig] = jwt.split('.');
  if (!sig) return null;
  const head = JSON.parse(new TextDecoder().decode(b64(h)));
  const claims = JSON.parse(new TextDecoder().decode(b64(p)));
  for (let attempt = 0; attempt < 2; attempt++) {
    if (!CERTS) CERTS = (await (await fetch(`https://${env.ACCESS_TEAM}/cdn-cgi/access/certs`)).json()).keys || [];
    const jwk = CERTS.find(k => k.kid === head.kid);
    if (!jwk) { CERTS = null; continue; }                // keys rotated: refetch once
    const key = await crypto.subtle.importKey('jwk', jwk, { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
    const ok = await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, b64(sig), new TextEncoder().encode(`${h}.${p}`));
    const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
    if (!ok || claims.exp * 1000 < Date.now() || !aud.includes(env.ACCESS_AUD)) return null;
    return String(claims.email || '').toLowerCase() || null;
  }
  return null;
}
const isOwner = (email, env) => !!email && String(env.OWNERS || '').toLowerCase().split(',').map(s => s.trim()).includes(email);

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

    const email = await accessEmail(request, env);
    if (url.pathname === '/api/me') return json({ ok: true, email, owner: isOwner(email, env) });
    if (!email) return json({ ok: false, error: 'Log in through the site first (Cloudflare Access).' }, 403);
    if (!isOwner(email, env)) return json({ ok: false, error: 'Only the site owner can run updates.' }, 403);
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
