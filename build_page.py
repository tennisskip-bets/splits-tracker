#!/usr/bin/env python3
"""Build docs/index.html (a phone-friendly page) from splits_log.csv.

One card per game from the latest snapshot. Each market (spread, total,
moneyline) gets a chart of the gap between money % and bets % for the first
listed side, with the line drawn as a step chart above it. Orange marks a line
move, a blue ring marks a jump of 5+ points in the gap, and gray shows missing
data or time after tip-off. Cards sort by tip-off time when tip_times.csv has it.
All times are Eastern, 12-hour. Information only, not betting advice.
"""
import csv
import html
import io
import math
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

LOG = "splits_log.csv"
TIPS = "tip_times.csv"
OUT = "docs/index.html"
ET = ZoneInfo("America/New_York")
MARKETS = [("spread", "Spread"), ("total", "Total"), ("moneyline", "Moneyline")]
MOVE_MIN = {"spread": 1.0, "total": 1.5}  # line move (points) needed for a reverse-move flag
LEAN_MIN = 60       # other side must hold at least this % of bets or money
JUMP_MIN = 5        # gap change between snapshots that gets a ring
FLIP_MIN = 20       # a majority flip must also swing this many points
DATA_GAP_MIN = 40   # minutes between snapshots that counts as missing data
FAST_MIN = 60       # a big move inside this many minutes is a fast move
FAST_PTS = {"spread": 1.5, "total": 2.0}
GAP_FLAGS = {"spread": 20, "total": 20, "moneyline": 30}
HIST_ROWS = 25
MAX_POINTS = 240


def now_et():
    s = os.environ.get("SPLITS_NOW")
    return datetime.fromisoformat(s).replace(tzinfo=ET) if s else datetime.now(ET)


NOW = now_et()


def read_rows():
    raw = open(LOG, "rb").read()
    try:
        txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        txt = raw.decode("cp1252")
    return list(csv.DictReader(io.StringIO(txt)))


def read_tips():
    out = {}
    if not os.path.exists(TIPS):
        return out
    for r in csv.DictReader(open(TIPS, encoding="utf-8-sig")):
        try:
            out[r["slug"]] = datetime.strptime(r["tip_et"], "%Y-%m-%d %H:%M").replace(tzinfo=ET)
        except (KeyError, ValueError):
            pass
    return out


def num(s):
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s or "")
    return float(m.group()) if m else None


def pct(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def clock(dt):
    return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def stamp(dt):
    return f"{dt.strftime('%a')} {clock(dt)}"


def day_word(dt):
    d = (dt.date() - NOW.date()).days
    if d == 0:
        return "Today"
    if d == 1:
        return "Tomorrow"
    return dt.strftime("%a")


ACRONYMS = {"lsu", "smu", "tcu", "usc", "ucf", "ucla", "unlv", "byu", "vcu", "utsa", "unc", "uconn",
            "njit", "uab", "fiu", "fgcu", "siu", "uic", "etsu", "liu", "umbc", "uncw", "utep"}


def pretty(slug):
    def team(p):
        return " ".join(w.upper() if w in ACRONYMS else w.title() for w in p.split("-"))
    return " vs ".join(team(p) for p in slug.split("-vs-"))


def fmt_line(market, x):
    if x is None:
        return ""
    return f"{x:+g}" if market == "spread" else f"{x:g}"


def prep(rows):
    out = []
    for r in sorted(rows, key=lambda r: r["t"]):
        b, m = r["bets_a"], r["money_a"]
        out.append({
            "t": r["t"], "a": r["side_a"], "b": r["side_b"], "line": num(r["line_a"]),
            "bets": b, "money": m,
            "gap": (m - b) if b is not None and m is not None else None,
        })
    return out


def mins(p, c):
    return (c["t"] - p["t"]).total_seconds() / 60


def analyze(market, snaps, tip):
    """Return (flags, notes). Flags use pregame snapshots only."""
    a, b = snaps[-1]["a"], snaps[-1]["b"]
    pre = [s for s in snaps if tip is None or s["t"] < tip]
    pp = [s for s in pre if s["gap"] is not None]
    ls = [s for s in pre if s["line"] is not None]
    flags, notes = [], []

    if market in MOVE_MIN and len(ls) >= 2 and pp:
        delta = ls[-1]["line"] - ls[0]["line"]
        if abs(delta) >= MOVE_MIN[market]:
            toward = a if ((delta < 0) if market == "spread" else (delta > 0)) else b
            other = b if toward == a else a
            lp = pp[-1]
            ob = lp["bets"] if other == a else 100 - lp["bets"]
            om = lp["money"] if other == a else 100 - lp["money"]
            parts = []
            if ob >= LEAN_MIN:
                parts.append(f"{ob}% of bets")
            if om >= LEAN_MIN:
                parts.append(f"{om}% of money")
            if parts:
                n = abs(delta)
                flags.append(f"Reverse move: line moved {n:g} pt{'s' if n != 1 else ''} toward "
                             f"{toward}, but {' and '.join(parts)} are on {other}")

    if market in MOVE_MIN:
        fast = None
        for p, c in zip(ls, ls[1:]):
            if mins(p, c) <= FAST_MIN and abs(c["line"] - p["line"]) >= FAST_PTS[market]:
                fast = (p, c)
        if fast:
            p, c = fast
            flags.append(f"Fast move: line went {fmt_line(market, p['line'])} to "
                         f"{fmt_line(market, c['line'])} between {clock(p['t'])} and {clock(c['t'])}")

    if len(pp) >= 2:
        for key, word in (("money", "Money"), ("bets", "Bets")):
            f0, f1 = pp[0][key], pp[-1][key]
            if (f0 - 50) * (f1 - 50) < 0 and abs(f1 - f0) >= FLIP_MIN:
                side = a if f1 > 50 else b
                was = f0 if side == a else 100 - f0
                now = f1 if side == a else 100 - f1
                notes.append(f"{word} flipped to {side}: {was}% to {now}%")

    if pp:
        g = pp[-1]["gap"]
        if abs(g) >= GAP_FLAGS[market]:
            side = a if g > 0 else b
            m = pp[-1]["money"] if side == a else 100 - pp[-1]["money"]
            bt = pp[-1]["bets"] if side == a else 100 - pp[-1]["bets"]
            flags.append(f"Money is {abs(g)} pts ahead of bets on {side}: {m}% of money on {bt}% of bets")

    gs = [s for s in snaps if s["gap"] is not None]
    best = None
    for p, c in zip(gs, gs[1:]):
        d = abs(c["gap"] - p["gap"])
        if d >= JUMP_MIN and (best is None or d > best[0]):
            best = (d, p, c)
    if best:
        _, p, c = best
        notes.append(f"Biggest gap move: {p['gap']:+d} to {c['gap']:+d} "
                     f"{'by' if mins(p, c) > DATA_GAP_MIN else 'at'} {stamp(c['t'])}")

    if market in MOVE_MIN:
        moves = []
        ls_all = [s for s in snaps if s["line"] is not None]
        for p, c in zip(ls_all, ls_all[1:]):
            if c["line"] != p["line"]:
                moves.append(f"{fmt_line(market, p['line'])} to {fmt_line(market, c['line'])} "
                             f"{'by' if mins(p, c) > DATA_GAP_MIN else 'at'} {clock(c['t'])}")
        if moves:
            notes.append("Line moves: " + "; ".join(moves[-3:]))
    return flags, notes


def thin(snaps):
    if len(snaps) <= MAX_POINTS:
        return snaps
    step = math.ceil(len(snaps) / MAX_POINTS)
    keep = []
    for i, s in enumerate(snaps):
        if i % step == 0 or i == len(snaps) - 1 or (i > 0 and s["line"] != snaps[i - 1]["line"]):
            keep.append(s)
    return keep


def ticks(t0, t1):
    dt0, dt1 = datetime.fromtimestamp(t0, ET), datetime.fromtimestamp(t1, ET)
    hours = (t1 - t0) / 3600
    step = next((s for s in (1, 2, 3, 4, 6, 12, 24) if hours / s <= 5), 24)
    cur = dt0.replace(minute=0, second=0, microsecond=0)
    while cur.hour % step != 0 or cur.timestamp() < t0:
        cur += timedelta(hours=1)
        if cur > dt1:
            return []
    out, multi = [], dt0.date() != dt1.date()
    while cur <= dt1:
        h = cur.hour
        lab = f"{h % 12 or 12}{'a' if h < 12 else 'p'}"
        if step >= 24:
            lab = cur.strftime("%a")
        elif multi and (h == 0 or not out):
            lab = cur.strftime("%a") + " " + lab
        out.append((cur.timestamp(), lab))
        cur += timedelta(hours=step)
    return out


def chart(snaps, tip, market, side):
    sn = thin(snaps)
    gs = [s for s in sn if s["gap"] is not None]
    if len(gs) < 2:
        return '<p class="sub">Not enough data for a chart yet.</p>'
    W, X0, X1 = 340, 30, 332
    t0, t1 = sn[0]["t"].timestamp(), sn[-1]["t"].timestamp()
    if t1 - t0 < 600:
        t1 = t0 + 600
    span = t1 - t0

    def sx(t):
        return X0 + (t - t0) / span * (X1 - X0)

    lines = [s for s in sn if s["line"] is not None]
    has_line = market != "moneyline" and len(lines) >= 1
    top1, H1 = 16, (50 if has_line else 0)
    top2 = top1 + (H1 + 14 if has_line else 0)
    H2 = 84
    H = top2 + H2 + 22
    bottom = top2 + H2
    gmax = max(20, math.ceil(max(abs(s["gap"]) for s in gs) / 10) * 10)

    def y2(v):
        return top2 + (gmax - v) / (2 * gmax) * H2

    p = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" '
         f'aria-label="Line and money minus bets gap for {html.escape(side)}">']

    for a, c in zip(sn, sn[1:]):
        if mins(a, c) > DATA_GAP_MIN:
            xa, xb = sx(a["t"].timestamp()), sx(c["t"].timestamp())
            p.append(f'<rect class="nd" x="{xa:.1f}" y="{top1}" width="{xb - xa:.1f}" height="{bottom - top1}"/>')
            if xb - xa > 46:
                p.append(f'<text class="tk" x="{(xa + xb) / 2:.1f}" y="{bottom - 4}" text-anchor="middle">no data</text>')

    if tip is not None and tip.timestamp() < t1:
        xt = max(X0, sx(tip.timestamp()))
        p.append(f'<rect class="nd" x="{xt:.1f}" y="{top1}" width="{X1 - xt:.1f}" height="{bottom - top1}"/>')
        p.append(f'<line class="tipl" x1="{xt:.1f}" x2="{xt:.1f}" y1="{top1}" y2="{bottom}"/>')
        if X1 - xt > 56:
            p.append(f'<text class="tk" x="{xt + 4:.1f}" y="{top1 + 11}">after tip</text>')

    if has_line:
        vals = [s["line"] for s in lines]
        lo, hi = min(vals) - 1, max(vals) + 1

        def y1(v):
            return top1 + (hi - v) / (hi - lo) * H1
        d = ""
        for i, s in enumerate(lines):
            x, y = sx(s["t"].timestamp()), y1(s["line"])
            d += f"M{x:.1f} {y:.1f}" if i == 0 else f"H{x:.1f}V{y:.1f}"
        p.append(f'<path class="ll" d="{d}"/>')
        p.append(f'<text class="tx" x="{X0}" y="11">first {fmt_line(market, vals[0])}</text>')
        p.append(f'<text class="tx" x="{X1}" y="11" text-anchor="end">now {fmt_line(market, vals[-1])}</text>')

    p.append(f'<line class="zl" x1="{X0}" x2="{X1}" y1="{y2(0):.1f}" y2="{y2(0):.1f}"/>')
    for v, lab in ((gmax, f"+{gmax}"), (0, "0"), (-gmax, f"-{gmax}")):
        p.append(f'<text class="tk" x="0" y="{y2(v) + 4:.1f}">{lab}</text>')

    d, prev = "", None
    for s in sn:
        if s["gap"] is None:
            prev = None
            continue
        brk = prev is None or mins(prev, s) > DATA_GAP_MIN
        d += f"{'M' if brk else 'L'}{sx(s['t'].timestamp()):.1f} {y2(s['gap']):.1f}"
        prev = s
    p.append(f'<path class="gl" d="{d}"/>')

    prev = None
    for s in sn:
        if prev is not None:
            x = sx(s["t"].timestamp())
            if has_line and s["line"] is not None and prev["line"] is not None and s["line"] != prev["line"]:
                p.append(f'<line class="mv" x1="{x:.1f}" x2="{x:.1f}" y1="{top1}" y2="{bottom}"/>')
                if s["gap"] is not None:
                    p.append(f'<circle class="dot" cx="{x:.1f}" cy="{y2(s["gap"]):.1f}" r="3.5"/>')
            if s["gap"] is not None and prev["gap"] is not None and abs(s["gap"] - prev["gap"]) >= JUMP_MIN:
                p.append(f'<circle class="ring" cx="{x:.1f}" cy="{y2(s["gap"]):.1f}" r="6"/>')
        prev = s

    for t, lab in ticks(t0, t1):
        p.append(f'<text class="tk" x="{sx(t):.1f}" y="{H - 4}" text-anchor="middle">{lab}</text>')
    p.append("</svg>")
    return "".join(p)


def history(market, snaps, side=""):
    side = html.escape(side)
    pre = {"total": "O/U ", "spread": f"{side} "}.get(market, "")
    rows, last_key = [], None
    for s in snaps:
        key = (s["line"], s["bets"], s["money"])
        if key != last_key:
            rows.append(s)
            last_key = key
    rows = rows[-HIST_ROWS:][::-1]
    body = "".join(
        f"<tr><td>{stamp(s['t'])}</td><td>{(pre + fmt_line(market, s['line'])) if s['line'] is not None else '-'}</td>"
        f"<td>{s['bets'] if s['bets'] is not None else '-'}</td>"
        f"<td>{s['money'] if s['money'] is not None else '-'}</td>"
        f"<td>{'%+d' % s['gap'] if s['gap'] is not None else '-'}</td></tr>" for s in rows)
    return ('<details><summary>History (changes only)</summary><table><tr><th>Time</th><th>Line</th>'
            f'<th>{side} bets %</th><th>{side} money %</th><th>Gap</th></tr>{body}</table></details>')


def market_block(market, label, snaps, tip):
    flags, notes = analyze(market, snaps, tip)
    last = snaps[-1]
    a, b = html.escape(last["a"]), html.escape(last["b"])
    ls = [s["line"] for s in snaps if s["line"] is not None]
    line_txt = ""
    if market != "moneyline" and ls:
        first, now = ls[0], ls[-1]
        if market == "spread":
            line_txt = f"{a} {fmt_line(market, first)} to {fmt_line(market, now)}" if first != now \
                else f"{a} {fmt_line(market, now)}"
        else:
            line_txt = f"{fmt_line(market, first)} to {fmt_line(market, now)}" if first != now \
                else f"{fmt_line(market, now)}"
    cur = next((s for s in reversed(snaps) if s["gap"] is not None), None)
    now_row = ""
    if cur:
        now_row = (f'<p class="now">Now on {a}: bets {cur["bets"]}% · money {cur["money"]}% · '
                   f'gap {cur["gap"]:+d}</p>')
    else:
        now_row = '<p class="now">Percentages not shown for the latest snapshot (a side is under about 5%).</p>'
    chips = "".join(f'<p class="flag">{html.escape(x)}</p>' for x in flags)
    chips += "".join(f'<p class="chip">{html.escape(x)}</p>' for x in notes)
    return len(flags), any(x.startswith("Reverse") for x in flags), (
        f'<div class="mk"><p class="h">{label}<span class="lnx">{line_txt}</span></p>'
        f'<p class="sides">Gap = money % minus bets % for {a} (vs {b})</p>{now_row}'
        f'{chart(snaps, tip, market, last["a"])}{chips}{history(market, snaps, last["a"])}</div>')


CSS = """
:root{--bg:#f6f6f4;--card:#fff;--text:#1c1c1a;--text2:#5d5d58;--muted:#8a8a85;--line:#e3e3df;--accent:#2f6fd6;--warn:#8a5a00;--warnbg:#fbf0d9;--nd:#ececea}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1e;--text:#ececea;--text2:#b5b5b0;--muted:#8d8d88;--line:#343432;--accent:#6aa0f0;--warn:#f0c56a;--warnbg:#3a2f14;--nd:#292928}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif}
main{max-width:520px;margin:0 auto;padding:16px}
h1{font-size:18px;font-weight:500;margin:0}.sub{color:var(--muted);font-size:12px;margin:2px 0 8px}
.warn{background:var(--warnbg);color:var(--warn);padding:8px 12px;border-radius:8px;font-size:13px;margin:0 0 12px}
.ctl{display:flex;gap:8px;align-items:center;margin:0 0 8px}
.ctl input[type=search]{flex:1;min-width:0;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--text);font-size:15px}
.ctl label{font-size:13px;color:var(--muted);white-space:nowrap}
.seg{display:flex;gap:8px;margin:0 0 12px;align-items:center;font-size:13px;color:var(--muted)}
.seg button{font:inherit;padding:4px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--text2)}
.seg button.on{background:var(--text);color:var(--bg);border-color:var(--text)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 12px}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.card h2{font-size:15px;font-weight:500;margin:0}.bd{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.badge.rev{background:var(--accent);color:var(--bg)}.badge{font-size:11px;background:var(--warnbg);color:var(--warn);padding:2px 8px;border-radius:8px;white-space:nowrap}
.mk{border-top:1px solid var(--line);margin-top:10px;padding-top:8px}
.h{font-size:13px;font-weight:500;margin:0;display:flex;justify-content:space-between;gap:8px}.lnx{font-weight:400;color:var(--text2)}
.sides{font-size:11px;color:var(--muted);margin:0}.now{font-size:12px;color:var(--text2);margin:2px 0 4px}
svg{display:block}.nd{fill:var(--nd)}.zl{stroke:var(--muted);stroke-dasharray:3 3}.gl{fill:none;stroke:var(--accent);stroke-width:2}
.ll{fill:none;stroke:var(--text);stroke-width:1.5}.mv{stroke:var(--warn);stroke-dasharray:2 3}.tipl{stroke:var(--muted);stroke-dasharray:2 3}
.dot{fill:var(--warn)}.ring{fill:none;stroke:var(--accent);stroke-width:1.5}.tk{fill:var(--muted);font-size:11px}.tx{fill:var(--text2);font-size:11px}
.flag{font-size:12px;background:var(--warnbg);color:var(--warn);padding:4px 8px;border-radius:6px;margin:6px 0 0}
.chip{font-size:12px;background:var(--bg);color:var(--text2);padding:4px 8px;border-radius:6px;margin:6px 0 0}
details{margin-top:6px}summary{font-size:12px;color:var(--muted);cursor:pointer}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:4px}th,td{text-align:left;padding:2px 4px;border-bottom:1px solid var(--line)}
.note{font-size:12px;color:var(--muted);margin:16px 0 0}
"""

JS = """
const q=document.getElementById('q'),f=document.getElementById('f'),r=document.getElementById('r'),list=document.getElementById('list');
function key(c){const t=+c.dataset.tip,now=Date.now()/1000;const g=!t?2:(t>=now?0:1);return [g,g===1?-t:(g===0?t:0)]}
function sortBy(k){const cs=[...list.children];cs.sort((a,b)=>{if(k==='flags'){const d=(+b.dataset.flags)-(+a.dataset.flags);if(d)return d}
const A=key(a),B=key(b);return A[0]-B[0]||A[1]-B[1]||a.dataset.n.localeCompare(b.dataset.n)});
cs.forEach(c=>list.appendChild(c));document.querySelectorAll('.seg:not(.days) button').forEach(x=>x.classList.toggle('on',x.dataset.k===k))}
let day='all';
function go(){const t=q.value.toLowerCase();document.querySelectorAll('.card').forEach(c=>{
c.style.display=(c.dataset.n.includes(t)&&(!f.checked||+c.dataset.flags>0)&&(!r.checked||+c.dataset.rev>0)&&(day==='all'||c.dataset.day===day))?'':'none'})}
q.addEventListener('input',go);f.addEventListener('change',go);r.addEventListener('change',go);
document.querySelectorAll('.seg:not(.days) button').forEach(x=>x.addEventListener('click',()=>sortBy(x.dataset.k)));
document.querySelectorAll('.days button').forEach(x=>x.addEventListener('click',()=>{day=x.dataset.d;document.querySelectorAll('.days button').forEach(y=>y.classList.toggle('on',y===x));go()}));
sortBy('start');
"""


def order_key(item):
    tip, name = item["tip"], item["name"]
    if tip is None:
        return (2, 0, name)
    ts = tip.timestamp()
    if tip >= NOW:
        return (0, ts, name)
    return (1, -ts, name)


def main():
    rows = read_rows()
    if not rows:
        raise SystemExit("splits_log.csv is empty")
    for r in rows:
        r["t"] = datetime.strptime(r["ts_et"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET)
        for k in ("bets_a", "bets_b", "money_a", "money_b"):
            r[k] = pct(r[k])
    latest = max(r["t"] for r in rows)
    # Keep games seen in the last 12 hours, so a snapshot that only has some games
    # (for example overnight, between days) doesn't make the other cards disappear.
    live = {r["slug"] for r in rows if (latest - r["t"]).total_seconds() <= 12 * 3600}
    data = {}
    for r in rows:
        if r["slug"] in live:
            data.setdefault(r["slug"], {}).setdefault(r["market"], []).append(r)
    tips = read_tips()

    games = []
    for slug, mk in data.items():
        tip = tips.get(slug)
        blocks, nflags, anyrev = [], 0, False
        for market, label in MARKETS:
            if market in mk:
                n, rev, blk = market_block(market, label, prep(mk[market]), tip)
                nflags += n
                anyrev = anyrev or rev
                blocks.append(blk)
        first_ts = min(r["t"] for v in mk.values() for r in v)
        if tip is None:
            status = "Tip time unknown"
        elif tip >= NOW:
            status = f"Tip {day_word(tip)} {clock(tip)} ET"
        else:
            status = f"Started {day_word(tip)} {clock(tip)} ET"
        badge = ""
        if anyrev:
            badge += '<span class="badge rev">Reverse move</span>'
        if nflags:
            badge += f'<span class="badge">{nflags} flag{"s" if nflags != 1 else ""}</span>'
        name = pretty(slug)
        card = (
            f'<div class="card" data-n="{html.escape(name.lower())}" '
            f'data-tip="{int(tip.timestamp()) if tip else 0}" data-flags="{nflags}" data-rev="{1 if anyrev else 0}" data-day="{(tip.date() - NOW.date()).days if tip else 0}">'
            f'<div class="top"><h2>{html.escape(name)}</h2><div class="bd">{badge}</div></div>'
            f'<p class="sub">{status} · tracking since {stamp(first_ts)}</p>{"".join(blocks)}</div>')
        games.append({"tip": tip, "name": name, "html": card})
    games.sort(key=order_key)

    age = (NOW - latest).total_seconds() / 60
    warn = (f'<p class="warn">Last snapshot is {age / 60:.1f} hours old, so the collector may be behind.</p>'
            if age > 45 else "")
    no_tips = ('<p class="warn">No tip times read yet, so cards are not sorted by start time.</p>'
               if not any(g["tip"] for g in games) else "")
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Splits tracker</title><style>{CSS}</style></head><body><main>'
        f'<h1>Splits tracker</h1><p class="sub">Last snapshot {stamp(latest)} ET · '
        f'{len(games)} games · {len({r["ts_et"] for r in rows})} snapshots</p>{warn}{no_tips}'
        '<div class="ctl"><input id="q" type="search" placeholder="Search a team"><label>'
        '<input id="f" type="checkbox"> Flagged</label><label>'
        '<input id="r" type="checkbox"> Reverse moves</label></div>'
        '<div class="seg"><span>Sort</span><button data-k="start" class="on">Start time</button>'
        '<button data-k="flags">Most flags</button></div>'
        '<div class="seg days"><span>Day</span><button data-d="all" class="on">All</button>'
        '<button data-d="-1">Yesterday</button><button data-d="0">Today</button>'
        '<button data-d="1">Tomorrow</button></div>'
        f'<div id="list">{"".join(g["html"] for g in games)}</div>'
        '<p class="note">Chart key: blue line is money % minus bets % for the first listed side (above 0 means '
        'money is heavier than tickets); the black step line is the market line; an orange dashed line marks a '
        'line move; a blue ring marks a gap jump of 5+ points; gray means no data or after tip-off. '
        'Line moves are measured from the first snapshot, not the true opening line. Flags only use '
        'snapshots before tip-off. Majority flips show as notes, not flags. A reverse move needs a 1-point spread move (1.5 on totals) toward one side '
        'while 60%+ of bets or money sit on the other. These are prompts to look closer, not betting '
        'advice, and reverse movement is not a proven edge.</p>'
        f'</main><script>{JS}</script></body></html>')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(page)
    print(f"wrote {OUT}: {len(games)} games, {len(page) // 1024} KB, "
          f"{sum(1 for g in games if g['tip'])} with tip times")


if __name__ == "__main__":
    main()
