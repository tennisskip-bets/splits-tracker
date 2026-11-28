#!/usr/bin/env python3
"""Snapshot % of bets / % of money from ScoresAndOdds NCAAB splits over time.

Usage:
  pip install requests beautifulsoup4 matplotlib
  python splits_tracker.py once                  # one snapshot -> splits_log.csv
  python splits_tracker.py once --debug          # print raw HTML of the first split block
  python splits_tracker.py run --every 15        # loop, snapshot every 15 min
  Options: --markets spread,total   --games utsa,georgia   (defaults: all three markets, all games)
  python splits_tracker.py plot georgia          # chart a game (substring of matchup slug)

Each row stores the timestamp (ET), the line at that moment, and bets/money % for
both sides, so you can see whether the splits drift as the number moves.
Keep the interval polite (10+ min) and check the site's terms before running long.
"""
import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

URL = "https://www.scoresandodds.com/ncaab/consensus-picks"
LOG = "splits_log.csv"
ET = ZoneInfo("America/New_York")
FIELDS = ["ts_et", "slug", "market", "side_a", "side_b", "line_a", "line_b",
          "bets_a", "bets_b", "money_a", "money_b", "raw"]

# e.g. "CHAR (-8.5) % of Bets UNI (+8.5) 57% 43% 69% 31% % of Money Best away ..."
BLOCK_RE = re.compile(
    r"^(?P<a>.+?)\s*% of Bets\s*(?P<b>.+?)\s+(?P<nums>(?:\d{1,3}%\s*)*)% of Money",
    re.S,
)
LABEL_RE = re.compile(r"^(?P<name>.*?)\s*\((?P<line>[^)]+)\)\s*$")
SLUG_RE = re.compile(r"/ncaab/[^/]+-vs-[^/]+$")


def fetch(date=None):
    params = {"date": date} if date else None
    r = requests.get(
        URL, params=params, timeout=30,
        headers=UA,
    )
    r.raise_for_status()
    return r.text


def split_label(label):
    m = LABEL_RE.match(label.strip())
    return (m.group("name").strip(), m.group("line").strip()) if m else (label.strip(), "")


def parse(html, debug=False):
    soup = BeautifulSoup(html, "html.parser")
    lis = [li for li in soup.find_all("li") if "% of Bets" in li.get_text()]
    # keep innermost blocks only
    lis = [li for li in lis if not any(o is not li and o in li.descendants for o in lis)]
    if debug and lis:
        print(lis[0].prettify()[:3000])
    ts = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for li in lis:
        text = li.get_text(" ", strip=True)
        m = BLOCK_RE.match(text)
        if not m:
            continue
        link = li.find_previous("a", href=SLUG_RE)
        slug = link["href"].rstrip("/").split("/")[-1] if link else "unknown"
        a_name, a_line = split_label(m.group("a"))
        b_name, b_line = split_label(m.group("b"))
        if a_name.lower().startswith("over"):
            market = "total"
        elif a_line:
            market = "spread"
        else:
            market = "moneyline"
        nums = [int(x) for x in re.findall(r"(\d{1,3})%", m.group("nums"))]
        # Order on the page: bets A, bets B, money A, money B.
        # If a side is under ~5% the page leaves it blank, so fewer than 4 numbers
        # is ambiguous; keep the raw text and leave the fields empty.
        vals = nums if len(nums) == 4 else [None] * 4
        rows.append({
            "ts_et": ts, "slug": slug, "market": market,
            "side_a": a_name, "side_b": b_name, "line_a": a_line, "line_b": b_line,
            "bets_a": vals[0], "bets_b": vals[1], "money_a": vals[2], "money_b": vals[3],
            "raw": text[:200] if None in vals else "",
        })
    return rows


def append(rows):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)


TIPS = "tip_times.csv"
MAIN_URL = "https://www.scoresandodds.com/ncaab"
UA = {"User-Agent": "Mozilla/5.0 (personal research script)"}
TIP_RE = re.compile(r"(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})\s*([AP]M)", re.I)


def parse_tips(html_text, now=None):
    """Read each game's tip-off time (ET) from the main NCAAB page.

    Returns ({slug: 'YYYY-MM-DD HH:MM'}, number of games seen). Each game's
    header (e.g. '11/26 1:30PM') is looked up in the table that precedes the
    game's Matchup link, so a game with no time is skipped, never guessed.
    """
    now = now or datetime.now(ET)
    soup = BeautifulSoup(html_text, "html.parser")
    tips, games = {}, set()
    for a in soup.find_all("a", href=SLUG_RE):
        slug = a["href"].split("?")[0].rstrip("/").split("/")[-1]
        if slug in games:
            continue
        games.add(slug)
        table = a.find_previous("table")
        m = TIP_RE.search(table.get_text(" ", strip=True)) if table else None
        if not m:
            continue
        mo, dy, hh, mm, ap = int(m[1]), int(m[2]), int(m[3]), int(m[4]), m[5].upper()
        hh = hh % 12 + (12 if ap == "PM" else 0)
        try:
            tip = datetime(now.year, mo, dy, hh, mm, tzinfo=ET)
        except ValueError:
            continue
        if (tip - now).days > 180:
            tip = tip.replace(year=now.year - 1)
        elif (now - tip).days > 180:
            tip = tip.replace(year=now.year + 1)
        tips[slug] = tip.strftime("%Y-%m-%d %H:%M")
    return tips, len(games)


def update_tips(date=None):
    """Save tip times to tip_times.csv. Never raises: collecting splits comes first."""
    try:
        r = requests.get(MAIN_URL, params={"date": date} if date else None,
                         timeout=30, headers=UA)
        r.raise_for_status()
        tips, n = parse_tips(r.text)
        old = {}
        if os.path.exists(TIPS):
            old = {x["slug"]: x for x in csv.DictReader(open(TIPS, encoding="utf-8-sig"))}
        stamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S")
        for slug, tip in tips.items():
            old[slug] = {"slug": slug, "tip_et": tip, "seen_et": stamp}
        cutoff = (datetime.now(ET) - timedelta(days=14)).strftime("%Y-%m-%d %H:%M")
        keep = sorted((v for v in old.values() if v["tip_et"] >= cutoff),
                      key=lambda v: v["tip_et"])
        with open(TIPS, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["slug", "tip_et", "seen_et"])
            w.writeheader()
            w.writerows(keep)
        print(f"tip times: read {len(tips)} of {n} games on the main page -> {TIPS}")
    except Exception as e:
        print("tip times skipped:", e, file=sys.stderr)


def snapshot(date=None, debug=False, markets=("spread", "total", "moneyline"), games=()):
    rows = parse(fetch(date), debug=debug)
    update_tips(date)
    rows = [r for r in rows if r["market"] in markets]
    if games:
        rows = [r for r in rows if any(g in r["slug"].lower() for g in games)]
    if not rows:
        print("No split blocks found. The page may be JS-rendered or its markup changed; "
              "re-run with --debug (or switch to Playwright).", file=sys.stderr)
        return 0
    append(rows)
    print(f"{rows[0]['ts_et']}  saved {len(rows)} rows -> {LOG}")
    return len(rows)


def plot(query):
    import matplotlib.pyplot as plt
    from datetime import datetime as dt

    rows = [r for r in csv.DictReader(open(LOG, encoding="utf-8-sig"))
            if query.lower() in r["slug"].lower() and r["market"] == "spread" and r["bets_a"]]
    if not rows:
        sys.exit(f"No spread rows with usable splits for '{query}' in {LOG}")
    x = [dt.strptime(r["ts_et"], "%Y-%m-%d %H:%M:%S") for r in rows]
    bets = [int(r["bets_a"]) for r in rows]
    money = [int(r["money_a"]) for r in rows]

    def num(s):
        try:
            return float(s)
        except ValueError:
            return None
    line = [num(r["line_a"]) for r in rows]
    a, b = rows[0]["side_a"], rows[0]["side_b"]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(x, bets, marker="o", label=f"% bets {a}")
    ax.plot(x, money, marker="s", label=f"% money {a}")
    ax.set_ylabel(f"% on {a}")
    ax.set_ylim(0, 100)
    ax2 = ax.twinx()
    ax2.step(x, line, where="post", color="gray", linestyle="--", label=f"{a} line")
    ax2.set_ylabel(f"{a} spread")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="best")
    ax.set_title(f"{rows[0]['slug']}  ({a} vs {b})")
    fig.autofmt_xdate()
    out = f"splits_{rows[0]['slug']}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print("saved", out)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("once", "run"):
        s = sub.add_parser(name)
        s.add_argument("--date", help="YYYY-MM-DD (default: site's current day)")
        s.add_argument("--debug", action="store_true")
        s.add_argument("--markets", default="spread,total,moneyline",
                       help="comma list of spread,total,moneyline (default all three)")
        s.add_argument("--games", default="",
                       help="comma list of words to match in the matchup, e.g. utsa,georgia (default: all)")
        if name == "run":
            s.add_argument("--every", type=float, default=15, help="minutes between snapshots")
    sp = sub.add_parser("plot")
    sp.add_argument("query", help="substring of the matchup slug, e.g. georgia")
    a = p.parse_args()

    if a.cmd in ("once", "run"):
        markets = tuple(m.strip() for m in a.markets.split(",") if m.strip())
        games = tuple(g.strip().lower() for g in a.games.split(",") if g.strip())
    if a.cmd == "once":
        snapshot(a.date, a.debug, markets, games)
    elif a.cmd == "run":
        while True:
            try:
                snapshot(a.date, a.debug, markets, games)
            except Exception as e:  # keep looping through transient errors
                print("error:", e, file=sys.stderr)
            time.sleep(a.every * 60)
    else:
        plot(a.query)


if __name__ == "__main__":
    main()
