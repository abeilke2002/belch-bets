// BetMGM and Caesars links need your state. When it isn't set yet, tapping one of those links asks for it right
// there, saves it (same 'bb-state' the page's picker uses), and gives you the link to open.
(function () {
  const STATES = ['az','co','ct','dc','ia','il','in','ks','ky','la','ma','md','mi','nc','nh','nj','ny','oh','pa','tn','va','vt','wv','wy'];
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  let dlg;
  function ask(url, name) {
    if (!dlg) {
      dlg = document.createElement('dialog');
      dlg.className = 'statedlg';
      document.body.appendChild(dlg);
      dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });
    }
    dlg.innerHTML = `<p><b>${esc(name)}</b> needs your state to open.</p>
      <select aria-label="Your state"><option value="">Choose your state</option>${STATES.map(c => `<option value="${c}">${c.toUpperCase()}</option>`).join('')}</select>
      <a class="go" target="_blank" rel="noopener noreferrer" hidden>Open ${esc(name)} ↗</a>
      <button type="button" class="x">Cancel</button>`;
    const sel = dlg.querySelector('select'), go = dlg.querySelector('.go');
    sel.onchange = () => {
      const st = sel.value;
      go.hidden = !st;
      if (!st) return;
      go.href = url.replaceAll('{state}', st);
      // let the page's own picker save it and redraw its links
      const pagePick = document.getElementById('state-sel');
      if (pagePick) { pagePick.value = st; pagePick.dispatchEvent(new Event('change')); }
      else { try { localStorage.setItem('bb-state', st); } catch (e) {} }
    };
    go.onclick = () => setTimeout(() => dlg.close(), 0);
    dlg.querySelector('.x').onclick = () => dlg.close();
    dlg.showModal();
  }
  document.addEventListener('click', e => {
    const a = e.target.closest && e.target.closest('a[href="#state"][data-url]');
    if (!a) return;
    e.preventDefault();
    ask(a.dataset.url, a.dataset.name || 'This sportsbook');
  });
})();
