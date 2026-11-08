"""Images for the X posts (post_x.py): one card per model for the noon picks and for the night's results.

    python x_cards.py            # writes today's cards to data/x_cards/*.png to look at

1200x675 PNG (X's 16:9), the site's dark theme and model colors. Picks: each bet with the projection (and its
± range) against the line on a small number line, and the chance to hit. Results: each bet's final against the
line, won or lost, the night and season records, and the model's running units this season.
"""
import io

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

BG, PANEL, LINE = '#0b0d10', '#12161c', '#232a33'
INK, INK2, MUTED = '#eceef1', '#b9c0ca', '#7d8794'
ACCENT, WIN, LOSS = '#e8a35c', '#4cc38a', '#ee6d64'
COLOR = {'points': '#e8a35c', 'rebounds': '#5fa8f0', 'assists': '#b58cf2'}
NAME = {'points': 'Points', 'rebounds': 'Rebounds', 'assists': 'Assists'}
UNIT = {'points': 'pts', 'rebounds': 'reb', 'assists': 'ast'}
BOOK = {'DraftKings': 'DK', 'FanDuel': 'FD', 'BetMGM': 'MGM', 'Caesars': 'CZR'}
W, H, DPI = 1200, 675, 200
MAX_ROWS = 5
plt.rcParams['font.family'] = 'DejaVu Sans'


def _fig():
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI, facecolor=BG)
    return fig


def _px(fig, x, y, s, size, color=INK, weight='normal', ha='left', va='baseline'):
    """Text at pixel (x, y) from the top-left; size in px."""
    fig.text(x / W, 1 - y / H, s, fontsize=size * 72 / DPI, color=color, weight=weight, ha=ha, va=va)


def _header(fig, market, title, date_label):
    _px(fig, 48, 58, 'THE NOON LINE', 15, ACCENT, 'bold')
    fig.patches.append(FancyBboxPatch((48 / W, 1 - 96 / H), 12 / W, 12 / H, boxstyle="square,pad=0",
                                      transform=fig.transFigure, color=COLOR[market]))
    _px(fig, 70, 104, title, 36, INK, 'bold')
    _px(fig, W - 48, 104, date_label, 20, INK2, ha='right')
    fig.add_artist(plt.Line2D([48 / W, 1 - 48 / W], [1 - 128 / H] * 2, color=LINE, lw=1, transform=fig.transFigure))


def _strip(fig, x0, x1, yc, lo, hi, marks, band=None, color=INK):
    """A small number line from lo to hi at pixel row yc: band (a, b) shaded, marks [(value, kind, label)]."""
    ax = fig.add_axes([x0 / W, 1 - (yc + 26) / H, (x1 - x0) / W, 52 / H])
    ax.set_xlim(lo, hi); ax.set_ylim(-1, 1); ax.axis('off')
    ax.plot([lo, hi], [0, 0], color=LINE, lw=2.2, solid_capstyle='round')
    if band:
        ax.fill_between([max(lo, band[0]), min(hi, band[1])], -0.2, 0.2, color=color, alpha=0.45, lw=0)
    for v, kind, label, c in marks:
        if kind == 'line':
            ax.plot([v, v], [-0.55, 0.55], color=c, lw=2.2, solid_capstyle='round')
            ax.text(v, -0.78, label, ha='center', va='top', fontsize=11 * 72 / DPI, color=c)
        else:
            ax.plot([v], [0], 'o', ms=7.5, color=c, mec=BG, mew=1.2)
            ax.text(v, 0.7, label, ha='center', va='bottom', fontsize=11 * 72 / DPI, color=c, weight='bold')


def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=DPI, facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


def _bounds(vals, pad=1.0):
    lo, hi = min(vals) - pad, max(vals) + pad
    return max(0.0, lo), hi


def picks_card(market, date_label, picks, records):
    """PNG bytes for one model's bets (best edge first), or None without bets. records: footer lines."""
    if not picks:
        return None
    fig = _fig()
    _header(fig, market, f'{NAME[market]} picks', date_label)
    shown = picks[:MAX_ROWS]
    top, bottom = 150, H - 92
    step = min(92, (bottom - top) / len(shown))
    _px(fig, W - 48, top + 6, 'CHANCE TO HIT', 11, MUTED, ha='right')
    _px(fig, 640, top + 6, 'PROJECTION VS LINE', 11, MUTED, ha='center')
    for i, p in enumerate(shown):
        y = top + 26 + step * (i + 0.5)
        side = 'Under' if p['side'] == 'UNDER' else 'Over'
        _px(fig, 48, y - 6, p['player'], 21, INK, 'bold')
        _px(fig, 48, y + 22, f"{side} {p['line']:g} {UNIT[market]} · {p['price']:+d} {BOOK.get(p['book'], p['book'])}", 15, INK2)
        sd = p.get('sigma') or 0
        lo, hi = _bounds([p['line'], p['proj'] - sd, p['proj'] + sd], pad=0.6)
        _strip(fig, 440, 840, y, lo, hi, [(p['line'], 'line', f"line {p['line']:g}", ACCENT),
                                          (p['proj'], 'proj', f"{p['proj']:.1f}", COLOR[market])],
               band=(p['proj'] - sd, p['proj'] + sd), color=COLOR[market])
        _px(fig, W - 48, y + 4, f"{p['p']:.0%}", 30, INK, 'bold', ha='right')
        if p.get('be') is not None:
            _px(fig, W - 48, y + 26, f"needs {p['be']:.0%}", 13, MUTED, ha='right')
        if i < len(shown) - 1:
            fig.add_artist(plt.Line2D([48 / W, 1 - 48 / W], [1 - (y + step / 2) / H] * 2, color=PANEL, lw=1,
                                      transform=fig.transFigure))
    more = f'  ·  +{len(picks) - MAX_ROWS} more in the thread' if len(picks) > MAX_ROWS else ''
    _px(fig, 48, H - 40, '   ·   '.join(records) + more, 15, INK2)
    _px(fig, W - 48, H - 40, 'shaded: model ± 1 sd', 12, MUTED, ha='right')
    return _png(fig)


def results_card(market, date_label, bets, records, season_units):
    """PNG bytes for one model's settled night, or None. season_units: the model's running units this season."""
    if not bets:
        return None
    fig = _fig()
    w = sum(b['result'] == 'win' for b in bets); l = sum(b['result'] == 'loss' for b in bets)
    u = sum(b.get('units') or 0 for b in bets)
    _header(fig, market, f'{NAME[market]} results', date_label)
    _px(fig, 48, 172, f'{w}-{l}', 44, INK, 'bold')
    _px(fig, 48 + 28 * len(f'{w}-{l}') + 14, 172, f"{'+' if u >= 0 else '−'}{abs(u):.2f}u", 30, WIN if u >= 0 else LOSS, 'bold')
    _px(fig, 48, 200, 'tonight', 13, MUTED)
    shown = bets[:MAX_ROWS]
    top, bottom = 228, H - 92
    step = min(80, (bottom - top) / len(shown))
    for i, b in enumerate(shown):
        y = top + step * (i + 0.5)
        side = 'U' if b['side'] == 'UNDER' else 'O'
        res = b['result']
        c = WIN if res == 'win' else LOSS if res == 'loss' else MUTED
        _px(fig, 48, y + 6, b['player'], 19, INK, 'bold')
        _px(fig, 330, y + 6, f"{side} {b['line']:g}", 17, INK2)
        if b.get('points') is not None:
            lo, hi = _bounds([b['line'], b['points']], pad=1.5)
            _strip(fig, 420, 700, y, lo, hi, [(b['line'], 'line', f"{b['line']:g}", ACCENT),
                                              (b['points'], 'proj', f"{b['points']:g}", c)])
        tag = {'win': 'W', 'loss': 'L', 'push': 'PUSH', 'void': 'VOID'}.get(res, res)
        _px(fig, 740, y + 7, tag, 19, c, 'bold')
    # running units for the model's season, bottom right
    if len(season_units) >= 3:
        ax = fig.add_axes([800 / W, 1 - (H - 100) / H, (W - 48 - 800) / W, (H - 100 - 210) / H])
        xs = range(len(season_units) + 1); ys = [0] + list(season_units)
        ax.axhline(0, color=LINE, lw=1)
        ax.plot(xs, ys, color=COLOR[market], lw=2)
        ax.fill_between(xs, ys, 0, color=COLOR[market], alpha=0.12, lw=0)
        ax.axis('off')
        ax.text(0, 1.04, f"{NAME[market]} season, running units", transform=ax.transAxes, fontsize=12 * 72 / DPI, color=MUTED)
        ax.text(1, 1.04, f"{'+' if ys[-1] >= 0 else '−'}{abs(ys[-1]):.1f}u", transform=ax.transAxes, ha='right',
                fontsize=13 * 72 / DPI, color=WIN if ys[-1] >= 0 else LOSS, weight='bold')
    more = f'  ·  +{len(bets) - MAX_ROWS} more' if len(bets) > MAX_ROWS else ''
    _px(fig, 48, H - 40, '   ·   '.join(records) + more, 15, INK2)
    return _png(fig)


if __name__ == '__main__':
    import json
    import post_x as X
    from config import DATA
    site = json.loads((DATA / 'site' / 'picks.json').read_text())
    out = DATA / 'x_cards'
    out.mkdir(exist_ok=True)
    for m, _ in X.MODELS:
        for kind, png in [('picks', X.picks_image(site, m)), ('results', X.results_image(site, m))]:
            if png:
                (out / f'{site["date"]}_{m}_{kind}.png').write_bytes(png)
                print('wrote', out / f'{site["date"]}_{m}_{kind}.png')
