// Shared by the Today (index.html) and Results (results.html) pages: formatting, sportsbook links, the model filter,
// season math and the running-units chart. The Board pages (points.html, rebounds/assists from market.html) keep their own.
(function (root) {
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const sgn = (v, d = 1) => { const a = Math.abs(v).toFixed(d); return (+a === 0 ? '' : v > 0 ? '+' : '−') + a; };
  const pct = (v, d = 1) => (v * 100).toFixed(d) + '%';
  const odds = p => (p > 0 ? '+' : '−') + Math.abs(p);
  const cls = v => Math.abs(v) < 0.05 ? '' : v > 0 ? 'pos' : 'neg';
  const cap = s => s === 'UNDER' ? 'Under' : 'Over';
  const longDate = s => new Date(s + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
  const short = s => new Date(s + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  const weekday = s => new Date(s + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long' });
  const monthName = m => new Date(m + '-15T12:00:00').toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
  const todayET = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date());
  const tipET = iso => iso ? new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) : '';
  const seasonOf = d => { const [y, mo] = d.split('-').map(Number), s = mo >= 8 ? y : y - 1; return `${s}-${String((s + 1) % 100).padStart(2, '0')}`; };
  const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
                  set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
  async function getJSON(p) { const r = await fetch(p, { cache: 'no-store' }); if (!r.ok) throw new Error(p + ' ' + r.status); return r.json(); }

  const MODELS = [{ m: 'points', name: 'Points', unit: 'pts', page: 'points.html', file: 'seasons.json', note: 'Both sides' },
                  { m: 'rebounds', name: 'Rebounds', unit: 'reb', page: 'rebounds.html', file: 'seasons_rebounds.json', note: 'Unders only' },
                  { m: 'assists', name: 'Assists', unit: 'ast', page: 'assists.html', file: 'seasons_assists.json', note: 'Both sides' }];
  const MODEL = Object.fromEntries(MODELS.map(M => [M.m, M]));
  const marketOf = b => b.market || 'points';                      // bets from before markets existed are points
  const settled = r => ['win', 'loss', 'void', 'push'].includes(r);
  const RES = { win: 'Won', loss: 'Lost', void: 'Void', push: 'Push' };

  // the model filter (All / Points / Rebounds / Assists), remembered across the Today and Results pages
  const getFilter = () => { const f = store.get('bb-filter'); return f && (f === 'all' || MODEL[f]) ? f : 'all'; };
  function filterSeg(box, onChange) {
    const cur = getFilter();
    box.innerHTML = [['all', 'All'], ...MODELS.map(M => [M.m, M.name])].map(([k, t]) =>
      `<button type="button" data-f="${k}" aria-pressed="${k === cur}">${k !== 'all' ? `<i class="mdot" style="--mc:var(--m-${k})"></i>` : ''}${t}</button>`).join('');
    box.querySelectorAll('button').forEach(b => b.onclick = () => {
      store.set('bb-filter', b.dataset.f);
      box.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      onChange(b.dataset.f);
    });
  }

  // sportsbook logos and links (bet slip where the book supports it; BetMGM and Caesars need your state)
  const LOGO = { DraftKings: 'draftkings', FanDuel: 'fanduel', BetMGM: 'betmgm', Caesars: 'caesars' };
  const STATES = ['az','co','ct','dc','ia','il','in','ks','ky','la','ma','md','mi','nc','nh','nj','ny','oh','pa','tn','va','vt','wv','wy'];
  const userState = () => store.get('bb-state') || '';
  const FALLBACK = { DraftKings: 'https://sportsbook.draftkings.com/leagues/basketball/nba', FanDuel: 'https://sportsbook.fanduel.com/navigation/nba',
                     BetMGM: 'https://sports.{state}.betmgm.com/en/sports/basketball-7/betting/usa-9/nba-6004', Caesars: 'https://sportsbook.caesars.com/us/{state}/bet/basketball' };
  const betUrl = url => !url ? null : !url.includes('{state}') ? url : userState() ? url.replaceAll('{state}', userState()) : '#state';
  function book(name, url) {
    const inner = `<span class="bk">${LOGO[name] ? `<img src="img/${LOGO[name]}.png" alt="">` : ''}${esc(name)}</span>`;
    const u = betUrl(url || FALLBACK[name]);
    if (!u) return inner;
    const tip = u === '#state' ? `Set your state at the bottom of the page to open ${name}` : url ? `Add this bet to your ${name} bet slip` : `Open ${name}`;
    return `<a class="bklink" href="${esc(u)}"${u !== '#state' ? ' target="_blank" rel="noopener noreferrer"' : ''} title="${esc(tip)}">${inner}</a>`;
  }
  function statePicker(sel, onChange) {
    sel.innerHTML = '<option value="">Choose</option>' + STATES.map(c => `<option value="${c}">${c.toUpperCase()}</option>`).join('');
    sel.value = userState();
    sel.onchange = () => { store.set('bb-state', sel.value); onChange(); };
  }

  // season math
  function sum(bets) {
    const L = bets.filter(b => b.result === 'win' || b.result === 'loss'), wins = L.filter(b => b.result === 'win').length;
    const all = bets.filter(b => settled(b.result));
    const units = all.reduce((s, b) => s + (b.units || 0), 0), risked = L.reduce((s, b) => s + (b.stake ?? 1), 0);
    return { n: L.length, wins, losses: L.length - wins, units, risked, roi: risked ? units / risked : 0 };
  }
  // 95% range for a season's units: each night's total is one draw (bets the same night move together)
  function unitsCI(bets) {
    const by = {};
    for (const b of bets) if (b.result === 'win' || b.result === 'loss') by[b.date] = (by[b.date] || 0) + b.units;
    const d = Object.values(by), n = d.length;
    if (n < 10) return null;
    const tot = d.reduce((a, x) => a + x, 0), m = tot / n;
    const pm = 1.96 * Math.sqrt(d.reduce((a, x) => a + (x - m) ** 2, 0) / (n - 1) * n);
    return { lo: tot - pm, hi: tot + pm, pm };
  }

  // running units by night (one point per day), with a hover readout
  function drawChart(bets, box) {
    const by = {};
    for (const b of bets) if (settled(b.result)) by[b.date] = (by[b.date] || 0) + (b.units || 0);
    const days = Object.keys(by).sort();
    if (!days.length) { box.innerHTML = '<p class="muted">The chart starts with the first settled bet.</p>'; return; }
    let c = 0; const pts = [0, ...days.map(d => (c += by[d]))], n = pts.length - 1;
    const W = Math.max(300, Math.round(box.clientWidth || 720)), H = W < 520 ? 200 : 240, m = { l: 42, r: 10, t: 12, b: 28 };
    const ymin = Math.min(0, ...pts), ymax = Math.max(0, ...pts), raw = (ymax - ymin) / 4;
    const mag = 10 ** Math.floor(Math.log10(Math.max(raw, 1))), step = [1, 2, 5, 10].map(k => k * mag).find(s => s >= raw) || 10 * mag;
    const y0 = Math.floor(ymin / step) * step, y1 = Math.max(Math.ceil(ymax / step) * step, y0 + step);
    const X = i => m.l + (i / Math.max(n, 1)) * (W - m.l - m.r), Y = v => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);
    let g = '';
    for (let v = y0; v <= y1 + 1e-9; v += step) g += `<line class="${Math.abs(v) < 1e-9 ? 'zero' : 'grid'}" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text class="tick" x="${m.l - 8}" y="${Y(v) + 4}" text-anchor="end">${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(+v.toFixed(6))}</text>`;
    [1, Math.round((n + 1) / 2), n].filter((v, i, a) => v >= 1 && a.indexOf(v) === i).forEach(i =>
      g += `<text class="tick" x="${X(i)}" y="${H - 8}" text-anchor="${i === 1 ? 'start' : i === n ? 'end' : 'middle'}">${short(days[i - 1])}</text>`);
    const line = pts.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' '), area = `${X(0)},${Y(0)} ${line} ${X(n)},${Y(0)}`;
    const id = box.id || 'c';
    box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Running units by night, now ${sgn(pts[n])} units after ${n} nights">
      <defs><clipPath id="${id}-ab"><rect width="${W}" height="${Y(0)}"/></clipPath><clipPath id="${id}-be"><rect y="${Y(0)}" width="${W}" height="${H}"/></clipPath></defs>
      ${g}<polygon class="up" points="${area}" clip-path="url(#${id}-ab)"/><polygon class="down" points="${area}" clip-path="url(#${id}-be)"/>
      <polyline class="line" points="${line}"/><g class="hv"><line class="guide" y1="${m.t}" y2="${H - m.b}"/><circle class="dot" r="4"/></g>
      <rect class="hit" x="${m.l}" y="0" width="${W - m.l - m.r}" height="${H}"/></svg><div class="tip" hidden></div>`;
    const svg = box.querySelector('svg'), tip = box.querySelector('.tip'), hv = svg.querySelector('.hv');
    svg.querySelector('.hit').addEventListener('pointermove', e => {
      const r = svg.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * W;
      const i = Math.max(1, Math.min(n, Math.round((x - m.l) / (W - m.l - m.r) * n)));
      hv.querySelector('.guide').setAttribute('x1', X(i)); hv.querySelector('.guide').setAttribute('x2', X(i));
      hv.querySelector('.dot').setAttribute('cx', X(i)); hv.querySelector('.dot').setAttribute('cy', Y(pts[i]));
      svg.classList.add('hover'); tip.hidden = false;
      tip.style.left = (X(i) / W * 100) + '%'; tip.style.top = (Y(pts[i]) / H * r.height) + 'px';
      tip.innerHTML = `${short(days[i - 1])}: ${sgn(by[days[i - 1]], 2)}u · season ${sgn(pts[i])}u`;
    });
    svg.querySelector('.hit').addEventListener('pointerleave', () => { svg.classList.remove('hover'); tip.hidden = true; });
  }

  const pill = r => `<span class="pill ${r === 'win' ? 'win' : r === 'loss' ? 'loss' : settled(r) ? 'other' : 'pending'}">${RES[r] || 'Pending'}</span>`;
  const mchip = m => `<span class="mchip" style="--mc:var(--m-${m})"><i class="mdot"></i>${MODEL[m].name}</span>`;

  root.NL = { $, esc, sgn, pct, odds, cls, cap, longDate, short, weekday, monthName, todayET, tipET, seasonOf, store, getJSON,
              MODELS, MODEL, marketOf, settled, RES, getFilter, filterSeg, book, statePicker, sum, unitsCI, drawChart, pill, mchip };
})(window);
