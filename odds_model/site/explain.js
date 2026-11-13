// The model's breakdown of a prop (explain.py, saved by the noon run as DATA.explain['market:PLAYER_ID']):
//   The bet       sportsbooks' chance -> the model's constant lean -> the projection's effect = model's chance, vs break-even
//   X drivers     the projection split into what pushed it up or down (bars add up to it)
//   Minutes       the same for the projected minutes the projection used
// XP.toggle(entry, book) returns a "Model breakdown" button plus its hidden panel; clicks are handled here.
(function () {
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const pct = v => (v * 100).toFixed(1) + '%';
  const pp = v => (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(1);
  const sg = v => (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(1);
  const odds = p => (p > 0 ? '+' : '−') + Math.abs(p);
  const WORD = { pt: ['pts', 'point'], reb: ['reb', 'rebound'], ast: ['ast', 'assist'] };
  const NAME = { pt: 'Points', reb: 'Rebounds', ast: 'Assists' };

  function betTab(e, book) {
    const x = e.bet, side = x.side === 'UNDER' ? 'under' : 'over', [u, word] = WORD[x.unit];
    const vals = [x.market, x.market + x.lean, x.p, x.need];
    const lo = Math.floor(Math.min(...vals) * 20) / 20 - 0.02, hi = Math.ceil(Math.max(...vals) * 20) / 20 + 0.02;
    const X = v => (v - lo) / (hi - lo) * 100;
    const seg = (a, c, cls) => `<span class="xseg ${cls}" style="left:${X(Math.min(a, c))}%;width:${Math.max(Math.abs(X(c) - X(a)), 0.6)}%"></span>`;
    const need = `<span class="xneed" style="left:${X(x.need)}%"></span>`;
    const gap = x.proj - e.line;
    const row = (l, sub, bar, n, cls = '') => `<div class="xw${cls}"><span class="xl">${l}${sub ? `<small>${sub}</small>` : ''}</span><span class="xt">${bar}${need}</span><span class="xn">${n}</span></div>`;
    return `<div class="xhead"><div class="xk">Chance the ${side} hits</div>
      <div class="xv">${pct(x.p)} <small>needs ${pct(x.need)} at ${odds(x.price)}${book ? ' ' + esc(book) : ''} · edge ${pp(x.p - x.need)}</small></div></div>
      <div class="xwf">
        ${row("Sportsbooks' chance", 'all books, vig removed', seg(lo, x.market, 'tot'), pct(x.market))}
        ${row("Model's general lean", 'a constant from training', seg(x.market, x.market + x.lean, x.lean >= 0 ? 'up' : 'dn'), pp(x.lean))}
        ${row(`Projection ${x.proj.toFixed(1)} vs line ${e.line}`, `${sg(gap)} ${u}, see the next tab`, seg(x.market + x.lean, x.p, x.proj_eff >= 0 ? 'up' : 'dn'), pp(x.proj_eff))}
        ${row("<b>Model's chance</b>", '', seg(lo, x.p, 'model'), pct(x.p))}
        ${row('Edge over break-even', `orange line: ${pct(x.need)} needed`, seg(x.need, x.p, x.p >= x.need ? 'up' : 'dn'), pp(x.p - x.need), ' xedge')}
        <div class="xscale"><span></span><div><span>${pct(lo)}</span><span>${pct((lo + hi) / 2)}</span><span>${pct(hi)}</span></div><span></span></div>
      </div>
      <p class="xfoot">The model starts from the sportsbooks' price and moves it by how far its projection is from the line.
        Each ${word} of projection moves the ${side} chance about ${Math.abs(x.per_unit * 100).toFixed(1)} points ${x.per_unit >= 0 ? 'up' : 'down'}.</p>`;
  }

  function driversTab(d, title, unit, side) {
    const show = d.drivers.filter(x => Math.abs(x.contrib) >= 0.05);
    const max = Math.max(...show.map(x => Math.abs(x.contrib)), 1e-9);
    const good = c => side === 'UNDER' ? c < 0 : c >= 0;              // helps the bet's side
    return `<div class="xhead"><div class="xk">${title}</div>
      <div class="xv">${d.pred.toFixed(1)} ${unit} <small>starts from ${d.base.toFixed(1)}, the average player</small></div></div>
      <div class="xrows">${show.map(x => {
        const w = Math.abs(x.contrib) / max * 34, pos = x.contrib >= 0;     // room for the number beside the longest bar
        return `<div class="xr"><span class="xl">${esc(x.label)}</span><span class="xtrack"><span class="xaxis"></span>
          <span class="xbar ${pos ? 'pos' : 'neg'} ${side ? (good(x.contrib) ? 'up' : 'dn') : 'nt'}" style="width:${w}%"></span>
          <span class="xnum" style="${pos ? `left:calc(${50 + w}% + 5px)` : `right:calc(${50 + w}% + 5px)`}">${sg(x.contrib)}</span></span>
          <span class="xval">${esc(x.value)}</span></div>`;
      }).join('')}</div>
      <p class="xfoot">Bars add up: ${d.base.toFixed(1)} ${show.map(x => sg(x.contrib)).join(' ')} = ${d.pred.toFixed(1)}.
        ${side ? `Green pushes toward the ${side === 'UNDER' ? 'under' : 'over'}, red against it.` : ''}</p>`;
  }

  function panel(e, book) {
    const tabs = [['The bet', betTab(e, book)], [`${NAME[e.bet.unit]} drivers`, driversTab(e.proj, 'Projection', WORD[e.bet.unit][0], e.bet.side)]];
    if (e.minutes) tabs.push(['Minutes drivers', driversTab(e.minutes, 'Projected minutes', 'min', null)]);
    return `<div class="xp"><div class="xtabs" role="tablist">${tabs.map(([t], i) => `<button type="button" role="tab" data-i="${i}" aria-selected="${i === 0}">${t}</button>`).join('')}</div>
      ${tabs.map(([, h], i) => `<div class="xbody" data-i="${i}"${i ? ' hidden' : ''}>${h}</div>`).join('')}
      <p class="xnote">From the noon model run. Your own lineup or minutes changes aren't reflected here.</p></div>`;
  }

  window.XP = {
    toggle(e, book) {
      if (!e || !e.bet) return '';
      return `<div class="xwrap"><button type="button" class="xbtn" aria-expanded="false">Model breakdown <span aria-hidden="true">▾</span></button>
        <div class="xpanel" hidden>${panel(e, book)}</div></div>`;
    },
  };

  document.addEventListener('click', ev => {
    const btn = ev.target.closest('.xbtn');
    if (btn) {
      ev.stopPropagation();
      const p = btn.nextElementSibling, open = p.hidden;
      p.hidden = !open; btn.setAttribute('aria-expanded', String(open));
      return;
    }
    const tab = ev.target.closest('.xtabs button');
    if (tab) {
      ev.stopPropagation();
      const root = tab.closest('.xp');
      root.querySelectorAll('.xtabs button').forEach(b => b.setAttribute('aria-selected', String(b === tab)));
      root.querySelectorAll('.xbody').forEach(b => { b.hidden = b.dataset.i !== tab.dataset.i; });
    }
  }, true);
})();
