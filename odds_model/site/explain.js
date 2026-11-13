// The model's breakdown of a prop (explain.py, saved by the noon run as DATA.explain['market:PLAYER_ID']):
//   X drivers     the projection split into what pushed it up or down (bars add up to it), with one line on the bet

//   Minutes       the same for the projected minutes the projection used
// XP.toggle(entry, book) returns a "Model breakdown" button plus its hidden panel; clicks are handled here.
(function () {
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const pct = v => (v * 100).toFixed(1) + '%';
  const sg = v => (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(1);
  const odds = p => (p > 0 ? '+' : '−') + Math.abs(p);
  const WORD = { pt: ['pts', 'point'], reb: ['reb', 'rebound'], ast: ['ast', 'assist'] };
  const NAME = { pt: 'Points', reb: 'Rebounds', ast: 'Assists' };

  function driversTab(d, title, unit, side, e, book) {
    const show = d.drivers.filter(x => Math.abs(x.contrib) >= 0.05);
    const max = Math.max(...show.map(x => Math.abs(x.contrib)), 1e-9);
    const good = c => side === 'UNDER' ? c < 0 : c >= 0;              // helps the bet's side
    return `<div class="xhead"><div class="xk">${title}</div>
      <div class="xv">${d.pred.toFixed(1)} ${unit} <small>starts from ${d.base.toFixed(1)}, the average player</small></div>
      ${e ? `<div class="xbetline">vs a <b>${e.line}</b> line · model gives the ${side === 'UNDER' ? 'under' : 'over'} <b>${pct(e.bet.p)}</b>, ${odds(e.bet.price)}${book ? ' ' + esc(book) : ''} needs ${pct(e.bet.need)}</div>` : ''}</div>
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
    const tabs = [[`${NAME[e.bet.unit]} drivers`, driversTab(e.proj, 'Projection', WORD[e.bet.unit][0], e.bet.side, e, book)]];
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
