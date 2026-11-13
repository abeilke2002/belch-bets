"""Images for the X posts (post_x.py): one card per model for the noon picks and for the night's results.

    python x_cards.py            # writes today's cards to data/x_cards/*.png to look at

1200x675 PNG (X's 16:9), the site's dark theme and model colors, drawn with matplotlib from the bets themselves.
Picks (the bet card): each bet with the projection (and its ± range) against the line on a small number line, and the
chance to hit next to the break-even. Results (the receipts): the night's record and units, each bet's final and
whether it won.
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
        size = f" · {p['stake']:g}u" if p.get('stake', 1) != 1 else ''
        _px(fig, 48, y + 22, f"{side} {p['line']:g} {UNIT[market]} · {p['price']:+d} {BOOK.get(p['book'], p['book'])}{size}", 15, INK2)
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


def results_card(market, date_label, bets, records):
    """PNG bytes for one model's settled night (the receipts: each bet, its final, won or lost), or None."""
    if not bets:
        return None
    fig = _fig()
    w = sum(b['result'] == 'win' for b in bets); l = sum(b['result'] == 'loss' for b in bets)
    u = sum(b.get('units') or 0 for b in bets)
    _header(fig, market, f'{NAME[market]} results', date_label)
    _px(fig, W / 2, 200, f"{w}-{l}   {'+' if u >= 0 else '−'}{abs(u):.2f}u", 40, WIN if u >= 0 else LOSS, 'bold', ha='center')
    shown = bets[:MAX_ROWS + 1] if len(bets) == MAX_ROWS + 1 else bets[:MAX_ROWS]
    top, bottom = 250, H - 80
    step = min(76, (bottom - top) / len(shown))
    size = 24 if step >= 64 else 20
    for i, b in enumerate(shown):
        y = top + step * (i + 0.5) + size / 3
        res = b['result']
        c = WIN if res == 'win' else LOSS if res == 'loss' else MUTED
        side = 'U' if b['side'] == 'UNDER' else 'O'
        _px(fig, 120, y, b['player'] + ('*' if b.get('added') else ''), size, INK, 'bold')
        _px(fig, 560, y, f"{side} {b['line']:g}", size - 2, INK2)
        final = f"{b['points']:g} {UNIT[market]}" if b.get('points') is not None else 'DNP'
        _px(fig, 760, y, final, size, INK, 'bold')
        _px(fig, 1000, y, {'win': 'WON', 'loss': 'LOST', 'push': 'PUSH', 'void': 'VOID'}.get(res, res.upper()), size - 2, c, 'bold')
    more = f'  ·  +{len(bets) - len(shown)} more' if len(bets) > len(shown) else ''
    _px(fig, 48, H - 40, '   ·   '.join(records) + more, 15, INK2)
    if any(b.get('added') for b in bets):
        _px(fig, W - 48, H - 40, '* added after a model fix', 13, MUTED, ha='right')
    return _png(fig)


def breakdown_card(market, date_label, pick, e):
    """PNG: the top bet explained. Left, the bet: sportsbooks' chance -> model's lean -> projection's effect = model's
    chance vs break-even. Right, what drove the projection (bars add up to it). e = picks.json explain entry."""
    if not e or not e.get('bet'):
        return None
    x, d = e['bet'], e['proj']
    under = x['side'] == 'UNDER'
    good, bad, grey, model = WIN, LOSS, '#5f6b7a', '#5fa8f0'
    fig = _fig()
    _header(fig, market, 'Top pick, explained', date_label)
    size = f" · {pick['stake']:g}u" if pick.get('stake', 1) != 1 else ''
    _px(fig, 48, 168, f"{pick['player']} · {'Under' if under else 'Over'} {pick['line']:g} {UNIT[market]} · "
                      f"{pick['price']:+d} {BOOK.get(pick['book'], pick['book'])} · edge {pick['edge']:+.1%}{size}", 20, INK, 'bold')
    # left: the bet, in chance for the side
    _px(fig, 48, 214, f"CHANCE THE {'UNDER' if under else 'OVER'} HITS", 12, MUTED)
    rows = [("Sportsbooks' chance", 0, x['market'], grey, f"{x['market']:.1%}"),
            ("Model's general lean", x['market'], x['market'] + x['lean'], good if x['lean'] >= 0 else bad, f"{x['lean'] * 100:+.1f}"),
            (f"Projection {x['proj']:.1f} vs {e['line']:g}", x['market'] + x['lean'], x['p'], good if x['proj_eff'] >= 0 else bad, f"{x['proj_eff'] * 100:+.1f}"),
            ("Model's chance", 0, x['p'], model, f"{x['p']:.1%}"),
            ('Edge over break-even', x['need'], x['p'], good if x['p'] >= x['need'] else bad, f"{(x['p'] - x['need']) * 100:+.1f}")]
    vals = [x['market'], x['market'] + x['lean'], x['p'], x['need']]
    lo, hi = min(vals) - 0.03, max(vals) + 0.03
    ax = fig.add_axes([250 / W, 1 - 560 / H, 240 / W, 320 / H])
    ax.set_xlim(lo, hi); ax.set_ylim(len(rows) - 0.4, -0.6); ax.axis('off')
    for i, (lab, a, b, c, txt) in enumerate(rows):
        a = max(a, lo)
        ax.barh(i, abs(b - a), left=min(a, b), height=0.56, color=c)
        ax.text(lo - (hi - lo) * 0.03, i, lab, ha='right', va='center', fontsize=12.5 * 72 / DPI, color=INK, weight='bold' if i == 3 else 'normal')
        ax.text(hi + (hi - lo) * 0.03, i, txt, ha='left', va='center', fontsize=13 * 72 / DPI, color=WIN if i == 4 else INK, weight='bold')
    ax.axvline(x['need'], color=ACCENT, lw=1.6)
    _px(fig, 48, 590, f"Orange line: {x['need']:.1%} needed at {x['price']:+d}. The model starts from the books' price", 12, MUTED)
    _px(fig, 48, 610, f"and moves it by how far its projection is from the line.", 12, MUTED)
    # right: the projection's drivers
    show = [r for r in d['drivers'] if abs(r['contrib']) >= 0.05][:7]
    _px(fig, 660, 214, f"WHY {d['pred']:.1f} {UNIT[market].upper()} · FROM {d['base']:.1f}, THE AVERAGE PLAYER", 12, MUTED)
    m = max(abs(r['contrib']) for r in show) or 1
    ax2 = fig.add_axes([830 / W, 1 - 560 / H, 230 / W, 320 / H])
    ax2.set_xlim(-m * 1.9, m * 1.9); ax2.set_ylim(len(show) - 0.4, -0.6); ax2.axis('off')
    ax2.axvline(0, color=LINE, lw=1)
    for i, r in enumerate(show):
        c = r['contrib']; helps = (c < 0) if under else (c >= 0)
        ax2.barh(i, c, height=0.56, color=good if helps else bad)
        ax2.text(c + (m * 0.06 if c >= 0 else -m * 0.06), i, f"{c:+.1f}", ha='left' if c >= 0 else 'right', va='center',
                 fontsize=12 * 72 / DPI, color=INK, weight='bold')
        ax2.text(-m * 1.95, i, r['label'], ha='right', va='center', fontsize=12.5 * 72 / DPI, color=INK)
        if r['value']:
            ax2.text(m * 1.95, i, r['value'], ha='left', va='center', fontsize=11.5 * 72 / DPI, color=MUTED)
    _px(fig, 660, 590, f"Green pushes toward the {'under' if under else 'over'}, red against it.", 12, MUTED)
    _px(fig, 660, 610, 'Bars add up to the projection.', 12, MUTED)
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
