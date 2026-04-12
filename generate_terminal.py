"""Terminal-themed GitHub profile SVG generator. Pulls live Codeforces + LeetCode stats.

Uses native SVG <text>/<rect> elements (no <foreignObject>) so it renders
through GitHub's image proxy.
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ─── config ─────────────────────────────────────────────────────────
CONFIG = {
    "cf_handle":   "evanap0330",
    "lc_handle":   "evanap0330",
    "name":        "Evan Phillips",
    "tagline":     "CS @ UNC Chapel Hill",
    "interests":   ["quant dev", "systems programming", "competitive programming"],
    "projects": [
        ("matching-engine/", "C++ low-latency order matching"),
        ("thanOS/",          "64-bit operating system from scratch"),
        ("lexem/",           "daily active users in production"),
    ],
    "cm_target":   1900,
    "show_codeforces": True,
    "show_leetcode":   True,
    "show_interests":  True,
    "show_projects":   True,
    "output":      "terminal.svg",
}

# ─── tokyo night palette ────────────────────────────────────────────
C = {
    "bg":        "#1a1b26",
    "bg_dark":   "#16161e",
    "border":    "#2a2b3d",
    "fg":        "#a9b1d6",
    "fg_bright": "#c0caf5",
    "comment":   "#565f89",
    "green":     "#9ece6a",
    "blue":      "#7aa2f7",
    "cyan":      "#89ddff",
    "purple":    "#bb9af7",
    "yellow":    "#e0af68",
    "red":       "#f7768e",
    "teal":      "#73daca",
}

# ─── layout ─────────────────────────────────────────────────────────
WIDTH       = 800
PAD_X       = 26
HEADER_H    = 36
BODY_TOP    = HEADER_H + 30
BODY_BOTTOM = 28
LINE_H      = 22
SECTION_GAP = 14
FONT        = "JetBrains Mono, Fira Code, SF Mono, Consolas, monospace"
FONT_SIZE   = 13
CHAR_W      = 7.85  # measured for ~13px monospace


# ─── data fetching ──────────────────────────────────────────────────
def http_json(url, data=None, headers=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_codeforces(handle):
    out = {
        "handle": handle, "rating": 0, "max_rating": 0,
        "rank": "unrated", "contests": 0, "ok": False,
    }
    headers = {"User-Agent": "evanap003300-readme-bot/1.0"}
    try:
        info = http_json(
            f"https://codeforces.com/api/user.info?handles={handle}",
            headers=headers,
        )
        if info.get("status") == "OK" and info.get("result"):
            u = info["result"][0]
            out["rating"] = u.get("rating", 0) or 0
            out["max_rating"] = u.get("maxRating", 0) or 0
            out["rank"] = u.get("rank", "unrated") or "unrated"
            out["ok"] = True

        rating_hist = http_json(
            f"https://codeforces.com/api/user.rating?handle={handle}",
            headers=headers,
        )
        if rating_hist.get("status") == "OK":
            out["contests"] = len(rating_hist.get("result", []))
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, IndexError, TimeoutError) as e:
        print(f"[warn] codeforces fetch failed: {e}", file=sys.stderr)
    return out


def fetch_leetcode(handle):
    out = {"total": 0, "easy": 0, "medium": 0, "hard": 0, "ok": False}
    query = """
    query ($username: String!) {
      matchedUser(username: $username) {
        submitStatsGlobal { acSubmissionNum { difficulty count } }
      }
    }
    """
    try:
        body = json.dumps({"query": query, "variables": {"username": handle}}).encode()
        resp = http_json(
            "https://leetcode.com/graphql",
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "evanap003300-readme-bot/1.0",
                "Referer": "https://leetcode.com",
            },
        )
        subs = resp["data"]["matchedUser"]["submitStatsGlobal"]["acSubmissionNum"]
        for s in subs:
            d = s["difficulty"].lower()
            if d == "all":
                out["total"] = s["count"]
            elif d in out:
                out[d] = s["count"]
        out["ok"] = True
    except (urllib.error.URLError, KeyError, TypeError, json.JSONDecodeError, TimeoutError) as e:
        print(f"[warn] leetcode fetch failed: {e}", file=sys.stderr)
    return out


# ─── svg helpers ────────────────────────────────────────────────────
def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def cf_rank_color(rank):
    return {
        "newbie":               C["comment"],
        "pupil":                C["green"],
        "specialist":           C["cyan"],
        "expert":               C["blue"],
        "candidate master":     C["purple"],
        "master":               C["yellow"],
        "international master": C["yellow"],
        "grandmaster":          C["red"],
        "international grandmaster": C["red"],
        "legendary grandmaster":     C["red"],
    }.get(str(rank).lower(), C["comment"])


class Builder:
    """Accumulates rows and emits positioned SVG."""

    def __init__(self):
        self.rows = []

    def text(self, *spans):
        self.rows.append(("text", spans))

    def gap(self):
        self.rows.append(("gap", None))

    def bar(self, value, target, label_left, label_right):
        self.rows.append(("bar", (value, target, label_left, label_right)))

    def cursor(self):
        self.rows.append(("cursor", None))

    def render_body(self):
        out = []
        y = BODY_TOP
        for kind, payload in self.rows:
            if kind == "text":
                out.append(self._text_row(y, payload))
                y += LINE_H
            elif kind == "bar":
                out.append(self._bar_row(y, *payload))
                y += LINE_H
            elif kind == "cursor":
                out.append(self._cursor_row(y))
                y += LINE_H
            elif kind == "gap":
                y += SECTION_GAP
        return "".join(out), y + BODY_BOTTOM

    @staticmethod
    def _text_row(y, spans):
        tspans = "".join(
            f'<tspan fill="{color}">{esc(text)}</tspan>' for text, color in spans
        )
        return f'<text x="{PAD_X}" y="{y}" xml:space="preserve">{tspans}</text>'

    @staticmethod
    def _bar_row(y, value, target, label_left, label_right):
        bar_w = 240
        bar_h = 8
        bar_x = PAD_X + len(label_left) * CHAR_W + 4
        bar_y = y - 9
        ratio = max(0.0, min(1.0, value / target if target else 0))
        return (
            f'<text x="{PAD_X}" y="{y}" xml:space="preserve" fill="{C["comment"]}">{esc(label_left)}</text>'
            f'<rect x="{bar_x:.1f}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="2" '
            f'fill="{C["bg_dark"]}" stroke="{C["border"]}"/>'
            f'<rect x="{bar_x:.1f}" y="{bar_y}" width="{bar_w * ratio:.1f}" height="{bar_h}" rx="2" '
            f'fill="{C["blue"]}"/>'
            f'<text x="{bar_x + bar_w + 10:.1f}" y="{y}" xml:space="preserve" fill="{C["fg"]}">{esc(label_right)}</text>'
        )

    @staticmethod
    def _cursor_row(y):
        return (
            f'<text x="{PAD_X}" y="{y}" xml:space="preserve">'
            f'<tspan fill="{C["green"]}">❯</tspan>'
            f'</text>'
            f'<rect x="{PAD_X + 16}" y="{y - 12}" width="8" height="14" fill="{C["fg_bright"]}">'
            f'<animate attributeName="opacity" values="1;0;1" dur="1.05s" repeatCount="indefinite"/>'
            f'</rect>'
        )


def build_terminal(cf, lc):
    cfg = CONFIG
    b = Builder()

    # whoami
    b.text(("❯ ", C["green"]), ("whoami", C["blue"]))
    b.text(
        (cfg["name"], C["fg_bright"]),
        ("  —  ", C["comment"]),
        (cfg["tagline"], C["purple"]),
    )

    if cfg["show_codeforces"]:
        b.gap()
        b.text(("❯ ", C["green"]), ("codeforces ", C["blue"]), ("--stats", C["cyan"]))
        b.text(
            ("  rating    ", C["comment"]),
            (str(cf["rating"]), C["red"]),
            ("  ", C["fg"]),
            (f"({cf['rank']})", cf_rank_color(cf["rank"])),
            ("    max ", C["comment"]),
            (str(cf["max_rating"]), C["fg"]),
        )
        b.text(
            ("  contests  ", C["comment"]),
            (str(cf["contests"]), C["fg_bright"]),
        )
        pct = int(min(100, (cf["rating"] / cfg["cm_target"]) * 100)) if cf["rating"] else 0
        b.bar(
            cf["rating"],
            cfg["cm_target"],
            label_left="  → cm     ",
            label_right=f"{cf['rating']} / {cfg['cm_target']}  ({pct}%)",
        )

    if cfg["show_leetcode"]:
        b.gap()
        b.text(("❯ ", C["green"]), ("leetcode ", C["blue"]), ("--solved", C["cyan"]))
        b.text(
            ("  total     ", C["comment"]),
            (str(lc["total"]), C["fg_bright"]),
        )
        b.text(
            ("  ", C["fg"]),
            (f"easy {lc['easy']}", C["green"]),
            ("    ", C["fg"]),
            (f"med {lc['medium']}", C["yellow"]),
            ("    ", C["fg"]),
            (f"hard {lc['hard']}", C["red"]),
        )

    if cfg["show_interests"]:
        b.gap()
        b.text(("❯ ", C["green"]), ("cat ", C["blue"]), ("interests.txt", C["cyan"]))
        spans = [("  ", C["fg"])]
        cols = [C["purple"], C["blue"], C["teal"]]
        for i, item in enumerate(cfg["interests"]):
            if i:
                spans.append(("  ·  ", C["comment"]))
            spans.append((item, cols[i % len(cols)]))
        b.text(*spans)

    if cfg["show_projects"]:
        b.gap()
        b.text(("❯ ", C["green"]), ("ls ", C["blue"]), ("~/projects", C["cyan"]))
        name_w = max(len(name) for name, _ in cfg["projects"]) + 2
        for name, desc in cfg["projects"]:
            b.text(
                ("  ", C["fg"]),
                (name.ljust(name_w), C["blue"]),
                (desc, C["comment"]),
            )

    b.gap()
    b.cursor()

    body_svg, height = b.render_body()
    now = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")

    header = (
        f'<rect x="0" y="0" width="{WIDTH}" height="{HEADER_H}" fill="{C["bg_dark"]}"/>'
        f'<line x1="0" y1="{HEADER_H}" x2="{WIDTH}" y2="{HEADER_H}" stroke="{C["border"]}"/>'
        f'<circle cx="22" cy="{HEADER_H/2}" r="6" fill="{C["red"]}"/>'
        f'<circle cx="42" cy="{HEADER_H/2}" r="6" fill="{C["yellow"]}"/>'
        f'<circle cx="62" cy="{HEADER_H/2}" r="6" fill="{C["green"]}"/>'
        f'<text x="{WIDTH/2}" y="{HEADER_H/2 + 4}" font-size="12" text-anchor="middle" '
        f'fill="{C["comment"]}">evan@github ~</text>'
        f'<text x="{WIDTH - PAD_X}" y="{HEADER_H/2 + 4}" font-size="10" text-anchor="end" '
        f'fill="{C["comment"]}">updated {esc(now)}</text>'
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" font-family="{FONT}" font-size="{FONT_SIZE}">'
        f'<defs><clipPath id="r"><rect x="0" y="0" width="{WIDTH}" height="{height}" rx="10" ry="10"/></clipPath></defs>'
        f'<g clip-path="url(#r)">'
        f'<rect width="{WIDTH}" height="{height}" fill="{C["bg"]}"/>'
        f'{header}'
        f'<g>{body_svg}</g>'
        f'</g>'
        f'<rect x="0.5" y="0.5" width="{WIDTH-1}" height="{height-1}" rx="10" ry="10" '
        f'fill="none" stroke="{C["border"]}"/>'
        f'</svg>'
    )


def main():
    print("fetching codeforces...", file=sys.stderr)
    cf = fetch_codeforces(CONFIG["cf_handle"])
    print(f"  rating={cf['rating']} rank={cf['rank']} contests={cf['contests']} ok={cf['ok']}", file=sys.stderr)

    print("fetching leetcode...", file=sys.stderr)
    lc = fetch_leetcode(CONFIG["lc_handle"])
    print(f"  total={lc['total']} ok={lc['ok']}", file=sys.stderr)

    svg = build_terminal(cf, lc)
    Path(CONFIG["output"]).write_text(svg, encoding="utf-8")
    print(f"wrote {CONFIG['output']} ({len(svg)} bytes)", file=sys.stderr)


if __name__ == "__main__":
    main()
