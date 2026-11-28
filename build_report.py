#!/usr/bin/env python3
"""Build docs/report.html: how line-move signals did against final scores.

Reads splits_log.csv, tip_times.csv and results.csv. For each game and market
(spread, total) it takes the pregame snapshots only, finds which side the line
moved toward, sorts the game into a group, and grades the side the line moved
toward against the closing line (the last pregame snapshot) and against the
first line we saw. Pushes are shown separately and left out of the win %.

Information only. A hit rate on a few games is noise, and -110 pricing means a
side needs to win about 52.4% just to break even.
"""
import csv
import html
import math
import os
from datetime import datetime

import build_page as bp

RESULTS = "results.csv"
OUT = "docs/report.html"
MIN_GAMES = 100  # below this per group, say so loudly

GROUPS = [
    ("reverse", "Reverse move",
     "Line moved toward a side while the other side held 60%+ of bets or money"),
    ("crowd", "Line moved with the crowd",
     "Line moved toward a side that held 60%+ of bets or money"),
    ("split", "Moved, no clear crowd",
     "Line moved, but neither side held 60% of bets or money"),
    ("nodata", "Moved, no percentages",
     "Line moved but the percentages were missing"),
]


def read_results():
    out = {}
    if not os.path.exists(RESULTS):
        return out
    for r in csv.DictReader(open(RESULTS, encoding="utf-8-sig")):
        try:
            out[r["slug"]] = {"away": r["away"], "home": r["home"],
                              "a": int(r["away_score"]), "h": int(r["home_score"])}
        except (KeyError, ValueError):
            pass
    return out


def outcome(market, res, line, toward_a):
    """Result for the side the line moved toward, against `line`."""
    if market == "spread":
        v = (res["a"] - res["h"]) + line          # >0 means away covers
    else:
        v = (res["a"] + res["h"]) - line          # >0 means Over
    if v == 0:
        return "push"
    a_wins = v > 0
    return "win" if a_wins == toward_a else "loss"


def signal(market, snaps, tip):
    """Group, direction and lines for one game-market, using pregame snapshots only."""
    pre = [s for s in snaps if tip is not None and s["t"] < tip]
    ls = [s for s in pre if s["line"] is not None]
    if len(ls) < 2:
        return None
    first, close = ls[0]["line"], ls[-1]["line"]
    delta = close - first
    if abs(delta) < bp.MOVE_MIN[market]:
        return {"group": None, "first": first, "close": close}
    toward_a = (delta < 0) if market == "spread" else (delta > 0)
    pp = [s for s in pre if s["gap"] is not None]
    if not pp:
        group = "nodata"
    else:
        lp = pp[-1]
        tb = lp["bets"] if toward_a else 100 - lp["bets"]
        tm = lp["money"] if toward_a else 100 - lp["money"]
        ob, om = 100 - tb, 100 - tm
        if ob >= bp.LEAN_MIN or om >= bp.LEAN_MIN:
            group = "reverse"
        elif tb >= bp.LEAN_MIN or tm >= bp.LEAN_MIN:
            group = "crowd"
        else:
            group = "split"
    return {"group": group, "toward_a": toward_a, "first": first, "close": close,
            "a": snaps[-1]["a"], "b": snaps[-1]["b"]}


def wilson(w, n, z=1.96):
    if n == 0:
        return None
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0, c - h), min(1, c + h)


def tally(items):
    w = sum(1 for x in items if x == "win")
    l = sum(1 for x in items if x == "loss")
    p = sum(1 for x in items if x == "push")
    return w, l, p


def cells(items):
    w, l, p = tally(items)
    n = w + l
    if n == 0:
        return f"<td>{len(items)}</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td>"
    lo, hi = wilson(w, n)
    return (f"<td>{len(items)}</td><td>{w}</td><td>{l}</td><td>{p}</td>"
            f"<td>{100 * w / n:.1f}%</td><td>{100 * lo:.0f}-{100 * hi:.0f}%</td>")


def main():
    rows = bp.read_rows()
    for r in rows:
        r["t"] = datetime.strptime(r["ts_et"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=bp.ET)
        for k in ("bets_a", "bets_b", "money_a", "money_b"):
            r[k] = bp.pct(r[k])
    tips, results = bp.read_tips(), read_results()
    data = {}
    for r in rows:
        data.setdefault(r["slug"], {}).setdefault(r["market"], []).append(r)

    graded = {m: {g[0]: {"close": [], "first": []} for g in GROUPS} for m in ("spread", "total")}
    base = {m: {"close": []} for m in ("spread", "total")}
    detail, n_games = [], 0
    for slug, mk in data.items():
        res, tip = results.get(slug), tips.get(slug)
        if not res or tip is None:
            continue
        n_games += 1
        for market in ("spread", "total"):
            if market not in mk:
                continue
            sig = signal(market, bp.prep(mk[market]), tip)
            if not sig:
                continue
            base[market]["close"].append(outcome(market, res, sig["close"], True))
            if not sig["group"]:
                continue
            oc = outcome(market, res, sig["close"], sig["toward_a"])
            of = outcome(market, res, sig["first"], sig["toward_a"])
            graded[market][sig["group"]]["close"].append(oc)
            graded[market][sig["group"]]["first"].append(of)
            if sig["group"] == "reverse":
                side = sig["a"] if sig["toward_a"] else sig["b"]
                detail.append((tip, bp.pretty(slug), market, side, sig["first"], sig["close"],
                               f"{res['away']} {res['a']}, {res['home']} {res['h']}", oc, of))

    parts = []
    for market, title in (("spread", "Spread"), ("total", "Total")):
        what = "side the line moved toward covered" if market == "spread" else "side the line moved toward hit (Over if the total went up)"
        body = ""
        for key, name, desc in GROUPS:
            g = graded[market][key]
            body += (f"<tr><td class='l'><b>{name}</b><br><small>{html.escape(desc)}</small></td>"
                     f"{cells(g['close'])}{cells(g['first'])}</tr>")
        b = base[market]["close"]
        # baseline: the away side (spread) or Over (total) against the closing line
        body += ("<tr><td class='l'><b>Baseline</b><br><small>"
                 f"{'Away team covers' if market == 'spread' else 'Over hits'}, every game with 2+ pregame snapshots"
                 f"</small></td>{cells(b)}<td colspan='6'></td></tr>")
        parts.append(
            f"<h2>{title}</h2><p class='sub'>Graded: {what}.</p><div class='tw'><table>"
            "<tr><th class='l' rowspan='2'>Group</th><th colspan='6'>Vs closing line</th>"
            "<th colspan='6'>Vs first line seen</th></tr>"
            + "<tr>" + "<th>Games</th><th>Won</th><th>Lost</th><th>Push</th><th>Win %</th><th>95% range</th>" * 2
            + f"</tr>{body}</table></div>")

    detail.sort(key=lambda x: x[0], reverse=True)
    drows = "".join(
        f"<tr><td class='l'>{html.escape(n)}<br><small>{m} · toward {html.escape(s)} · "
        f"{bp.fmt_line(m, f)} to {bp.fmt_line(m, c)}</small></td><td>{html.escape(sc)}</td>"
        f"<td>{oc}</td><td>{of}</td></tr>" for _, n, m, s, f, c, sc, oc, of in detail[:40])
    small = max((len(graded[m]["reverse"]["close"]) for m in graded), default=0) < MIN_GAMES
    warn = (f"<div class='warn'>Only {n_games} finished games have been graded so far, and the reverse-move "
            f"groups are well under {MIN_GAMES} games. Treat every percentage below as noise until the "
            "samples are much larger. The 95% range shows how wide the uncertainty still is.</div>"
            if small else "")
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Results report</title><style>{bp.CSS}{EXTRA}</style></head><body><main>"
        "<h1>Results report</h1>"
        f'<p class="sub">{n_games} finished games graded · updated {bp.stamp(bp.NOW)} ET · '
        '<a href="index.html">Back to games</a></p>' + warn + "".join(parts) +
        "<h2>Recent reverse moves</h2><div class='tw'><table><tr><th class='l'>Game</th><th>Final</th>"
        f"<th>Vs close</th><th>Vs first</th></tr>{drows or '<tr><td class=l colspan=4>None graded yet</td></tr>'}</table></div>"
        '<p class="note">How to read this: only snapshots taken before tip-off are used. "Moved toward" is the '
        "side whose price got worse for bettors (the spread side getting fewer points, or the Over when the total "
        "rose). Grades use the closing line (our last pregame snapshot, up to 15 minutes before tip) and the first "
        "line we saw, which is not the true opening line. Pushes are excluded from Win %. At standard -110 pricing "
        "a side needs about 52.4% to break even. Groups are not independent: spread and total from the same game "
        "are both counted. Results here describe the past, not a prediction. Information only, not betting advice.</p>"
        "</main></body></html>")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(page)
    print(f"wrote {OUT}: {n_games} graded games, {len(detail)} reverse moves")


EXTRA = """
.tw{overflow-x:auto}table{border-collapse:collapse;font-size:12px;margin:6px 0 14px}
th,td{padding:5px 7px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
td.l,th.l{text-align:left;white-space:normal;min-width:150px}
h2{font-size:16px;font-weight:500;margin:18px 0 2px}main{max-width:760px}
"""

if __name__ == "__main__":
    main()
