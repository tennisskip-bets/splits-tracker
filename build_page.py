#!/usr/bin/env python3
"""Build docs/index.html (a phone-friendly page) from splits_log.csv.

One card per game from the latest snapshot. For spread and total it shows the
line change since the first snapshot, bets/money for side A, and flags
reverse line movement (line moves toward one side while most bets or money
are on the other) and big money-vs-bets gaps. Moneyline shows splits only,
because the log stores no moneyline number.
"""
import csv
import html
import io
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

LOG = "splits_log.csv"
OUT = "docs/index.html"
ET = ZoneInfo("America/New_York")
MARKETS = [("spread", "Spread"), ("total", "Total"), ("moneyline", "Moneyline")]
GAP_FLAG = 15  # money% minus bets% needed to flag a gap


def read_rows():
    raw = open(LOG, "rb").read()
    try:
        txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        txt = raw.decode("cp1252")
    return list(csv.DictReader(io.StringIO(txt)))


def num(s):
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s or "")
    return float(m.group()) if m else None


def pct(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def fmt_line(x):
    if x is None:
        return ""
    return f"{x:+g}" if x else "0"


def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET)


ACRONYMS = {"lsu", "smu", "tcu", "usc", "ucf", "ucla", "unlv", "byu", "vcu", "utsa", "unc", "uconn",
            "njit", "uab", "fiu", "fgcu", "siu", "uic", "etsu", "liu", "umbc", "uncw", "utep", "uab"}


def pretty(slug):
    def team(p):
        return " ".join(w.upper() if w in ACRONYMS else w.title() for w in p.split("-"))
    return " vs ".join(team(p) for p in slug.split("-vs-"))


def direction(market, first, last):
    if first is None or last is None or first == last:
        return None
    if market == "spread":
        return "A" if last < first else "B"
    if market == "total":
        return "A" if last > first else "B"
    return None


def majority(a):
    if a is None or a == 50:
        return None
    return "A" if a > 50 else "B"


def first_with(snaps, key):
    for s in snaps:
        if s[key] is not None:
            return s
    return None


def spark(snaps):
    pts = [s for s in snaps if s["bets_a"] is not None and s["money_a"] is not None]
    if len(pts) < 2:
        return ""
    t0, t1 = pts[0]["t"].timestamp(), pts[-1]["t"].timestamp()
    span = (t1 - t0) or 1

    def line(key):
        return " ".join(
            f"{(p['t'].timestamp() - t0) / span * 118 + 1:.1f},{29 - p[key] / 100 * 28:.1f}"
            for p in pts)
    return (
        '<svg viewBox="0 0 120 30" width="120" height="30" role="img" aria-label="bets and money trend">'
        f'<polyline points="{line("bets_a")}" fill="none" stroke="var(--muted)" stroke-width="1.5"/>'
        f'<polyline points="{line("money_a")}" fill="none" stroke="var(--accent)" stroke-width="1.5"/>'
        "</svg>")


def market_block(market, label, snaps):
    last = snaps[-1]
    a, b = html.escape(last["side_a"]), html.escape(last["side_b"])
    f = first_with(snaps, "bets_a") or last
    flags = []
    l_first, l_last = num(f["line_a"]), num(last["line_a"])
    if market != "moneyline":
        d = direction(market, l_first, l_last)
    else:
        d = None
    if d:
        toward = a if d == "A" else b
        for key, word in (("bets", "bets"), ("money", "money")):
            maj = majority(last[f"{key}_a"])
            if maj and maj != d:
                share = last[f"{key}_a"] if maj == "A" else 100 - last[f"{key}_a"]
                other = a if maj == "A" else b
                flags.append(f"Line moved toward {toward}, but {share}% of {word} is on {other}")
    if last["bets_a"] is not None and last["money_a"] is not None:
        gap = last["money_a"] - last["bets_a"]
        if abs(gap) >= GAP_FLAG:
            who = a if gap > 0 else b
            flags.append(f"Money runs {abs(gap)} pts ahead of bets on {who}")

    line_txt = ""
    if market != "moneyline" and l_last is not None:
        if l_first is not None and l_first != l_last:
            line_txt = f"{a} {fmt_line(l_first)} → {fmt_line(l_last)}" if market == "spread" \
                else f"{html.escape(last['side_a'].split()[0])} {l_first:g} → {l_last:g}"
        else:
            line_txt = f"{a} {fmt_line(l_last)}" if market == "spread" else f"Total {l_last:g}"

    def row(name, key):
        v, v0 = last[f"{key}_a"], f[f"{key}_a"]
        if v is None:
            return (f'<div class="r"><span class="k">{name}</span>'
                    '<span class="m">not shown (side under ~5%)</span></div>')
        delta = "" if v0 is None or v0 == v else f'<span class="d">{v - v0:+d}</span>'
        cls = "bar acc" if key == "money" else "bar"
        return (f'<div class="r"><span class="k">{name}</span>'
                f'<span class="t"><span class="{cls}" style="width:{v}%"></span></span>'
                f'<span class="v">{v}% / {100 - v}%</span>{delta}</div>')

    hist = "".join(
        f"<tr><td>{s['t'].strftime('%m-%d %H:%M')}</td><td>{html.escape(s['line_a'] or '-')}</td>"
        f"<td>{s['bets_a'] if s['bets_a'] is not None else '-'}</td>"
        f"<td>{s['money_a'] if s['money_a'] is not None else '-'}</td></tr>"
        for s in reversed(snaps[-80:]))
    flag_html = "".join(f'<p class="flag">{html.escape(x)}</p>' for x in flags)
    return flags, (
        f'<div class="mk"><p class="h">{label}'
        f'{"<span class=ln>" + line_txt + "</span>" if line_txt else ""}</p>'
        f'<p class="sides">{a} / {b} · % shown for {a}</p>'
        f'{row("Bets", "bets")}{row("Money", "money")}'
        f'<div class="sp">{spark(snaps)}</div>{flag_html}'
        f'<details><summary>History</summary><table><tr><th>Time</th><th>Line</th>'
        f'<th>Bets</th><th>Money</th></tr>{hist}</table></details></div>')


CSS = """
:root{--bg:#f6f6f4;--card:#fff;--text:#1c1c1a;--muted:#8a8a85;--line:#e3e3df;--accent:#2f6fd6;--warn:#8a5a00;--warnbg:#fbf0d9}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1e;--text:#ececea;--muted:#8d8d88;--line:#343432;--accent:#6aa0f0;--warn:#f0c56a;--warnbg:#3a2f14}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif}
main{max-width:520px;margin:0 auto;padding:16px}
h1{font-size:18px;font-weight:500;margin:0}.sub{color:var(--muted);font-size:12px;margin:2px 0 12px}
.warn{background:var(--warnbg);color:var(--warn);padding:8px 12px;border-radius:8px;font-size:13px;margin:0 0 12px}
.ctl{display:flex;gap:8px;align-items:center;margin:0 0 12px}
.ctl input[type=search]{flex:1;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--text);font-size:15px}
.ctl label{font-size:13px;color:var(--muted);white-space:nowrap}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 12px}
.card h2{font-size:15px;font-weight:500;margin:0}.badge{font-size:11px;background:var(--warnbg);color:var(--warn);padding:2px 8px;border-radius:8px;margin-left:8px;white-space:nowrap}
.mk{border-top:1px solid var(--line);margin-top:10px;padding-top:8px}
.h{font-size:12px;color:var(--muted);margin:0;display:flex;justify-content:space-between}.ln{color:var(--text)}
.sides{font-size:11px;color:var(--muted);margin:0 0 4px}
.r{display:flex;align-items:center;gap:8px;font-size:13px;margin:2px 0}.k{width:44px;color:var(--muted);font-size:12px}
.t{flex:1;height:6px;background:var(--line);border-radius:3px;overflow:hidden}.bar{display:block;height:6px;background:var(--muted)}.bar.acc{background:var(--accent)}
.v{min-width:74px;text-align:right}.d{width:30px;text-align:right;color:var(--muted);font-size:12px}
.sp{margin:4px 0 0}.flag{font-size:12px;background:var(--warnbg);color:var(--warn);padding:4px 8px;border-radius:6px;margin:6px 0 0}
details{margin-top:6px}summary{font-size:12px;color:var(--muted);cursor:pointer}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:4px}th,td{text-align:left;padding:2px 4px;border-bottom:1px solid var(--line)}
.note{font-size:12px;color:var(--muted);margin:16px 0 0}
"""

JS = """
const q=document.getElementById('q'),f=document.getElementById('f');
function go(){const t=q.value.toLowerCase();document.querySelectorAll('.card').forEach(c=>{
c.style.display=(c.dataset.n.includes(t)&&(!f.checked||c.dataset.f==='1'))?'':'none'})}
q.addEventListener('input',go);f.addEventListener('change',go);
"""


def main():
    rows = read_rows()
    if not rows:
        raise SystemExit("splits_log.csv is empty")
    for r in rows:
        r["t"] = parse_ts(r["ts_et"])
        r["bets_a"], r["bets_b"] = pct(r["bets_a"]), pct(r["bets_b"])
        r["money_a"], r["money_b"] = pct(r["money_a"]), pct(r["money_b"])
    latest = max(r["t"] for r in rows)
    live = {r["slug"] for r in rows if r["t"] == latest}
    data = {}
    for r in sorted(rows, key=lambda r: r["t"]):
        if r["slug"] in live:
            data.setdefault(r["slug"], {}).setdefault(r["market"], []).append(r)

    cards = []
    for slug, mk in data.items():
        all_flags, blocks = [], []
        for market, label in MARKETS:
            if market in mk:
                fl, blk = market_block(market, label, mk[market])
                if market != "moneyline":
                    all_flags += [x for x in fl if x.startswith("Line moved")]
                else:
                    all_flags += fl
                blocks.append(blk)
        badge = '<span class="badge">Line vs bets/money</span>' if any(
            x.startswith("Line moved") for x in all_flags) else ""
        first_ts = min(s["t"] for v in mk.values() for s in v)
        cards.append((0 if badge else 1, pretty(slug), (
            f'<div class="card" data-n="{html.escape(pretty(slug).lower())}" data-f="{1 if badge else 0}">'
            f'<h2>{html.escape(pretty(slug))}{badge}</h2>'
            f'<p class="sub">Tracking since {first_ts.strftime("%m-%d %H:%M")} ET</p>'
            f'{"".join(blocks)}</div>')))
    cards.sort(key=lambda c: (c[0], c[1]))

    now = datetime.now(ET)
    age_min = (now - latest).total_seconds() / 60
    warn = (f'<p class="warn">Last snapshot is {age_min / 60:.1f} hours old, so the collector may be behind.</p>'
            if age_min > 45 else "")
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Splits tracker</title><style>{CSS}</style></head><body><main>'
        f'<h1>Splits tracker</h1><p class="sub">Last snapshot {latest.strftime("%a %m-%d %H:%M")} ET · '
        f'{len(cards)} games · {len({r["ts_et"] for r in rows})} snapshots</p>{warn}'
        '<div class="ctl"><input id="q" type="search" placeholder="Search a team"><label>'
        '<input id="f" type="checkbox"> Flagged only</label></div>'
        f'{"".join(c[2] for c in cards)}'
        '<p class="note">Flags compare the line now with the first snapshot, not the true opening line. '
        'Line vs bets/money means the line moved toward one side while most bets or money are on the other. '
        'Information only, not betting advice.</p>'
        f'</main><script>{JS}</script></body></html>')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(page)
    print(f"wrote {OUT}: {len(cards)} games, {len(page) // 1024} KB")


if __name__ == "__main__":
    main()
