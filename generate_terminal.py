"""Terminal-themed GitHub profile SVG generator. Pulls live Codeforces + LeetCode stats.

Uses native SVG <text>/<rect> with SMIL <animate> for a typing animation that loops.
No <foreignObject>, so it renders through GitHub's image proxy.
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
        ("yolo-to-3d/",      "drone YOLO → 3D OptiTrack coords · paper"),
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

# ─── animation timing (seconds) ─────────────────────────────────────
CHAR_DUR            = 0.020   # per-character typing speed
INITIAL_DELAY       = 0.25    # blank pause at the start of each cycle
LINE_PAUSE          = 0.08    # pause between consecutive lines
SECTION_PAUSE_EXTRA = 0.30    # extra pause when a line follows a gap
HOLD_AT_END         = 2.6     # how long the finished terminal stays visible
MIN_LINE_DUR        = 0.18    # minimum reveal time for any single line


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


# ─── row model + builder ────────────────────────────────────────────
class Row:
    __slots__ = ("kind", "draw_fn", "px_width", "follows_gap", "y")

    def __init__(self, kind, draw_fn, px_width):
        self.kind = kind
        self.draw_fn = draw_fn
        self.px_width = px_width
        self.follows_gap = False
        self.y = 0


class Builder:
    def __init__(self):
        self.rows = []
        self._pending_gap = False

    def _add(self, row):
        row.follows_gap = self._pending_gap
        self._pending_gap = False
        self.rows.append(row)

    def gap(self):
        self._pending_gap = True

    def text(self, *spans):
        full = "".join(t for t, _ in spans)
        px = len(full) * CHAR_W

        def draw(y, clip_id):
            tspans = "".join(
                f'<tspan fill="{color}">{esc(text)}</tspan>'
                for text, color in spans
            )
            return (
                f'<g clip-path="url(#{clip_id})">'
                f'<text x="{PAD_X}" y="{y}" xml:space="preserve">{tspans}</text>'
                f'</g>'
            )

        self._add(Row("text", draw, px))

    def bar(self, value, target, label_left, label_right):
        bar_w = 240
        bar_h = 8
        ratio = max(0.0, min(1.0, value / target if target else 0))
        left_chars = len(label_left)
        right_chars = len(label_right)
        total_px = left_chars * CHAR_W + 4 + bar_w + 10 + right_chars * CHAR_W

        def draw(y, clip_id):
            bar_x = PAD_X + left_chars * CHAR_W + 4
            bar_y = y - 9
            return (
                f'<g clip-path="url(#{clip_id})">'
                f'<text x="{PAD_X}" y="{y}" xml:space="preserve" fill="{C["comment"]}">{esc(label_left)}</text>'
                f'<rect x="{bar_x:.1f}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="2" '
                f'fill="{C["bg_dark"]}" stroke="{C["border"]}"/>'
                f'<rect x="{bar_x:.1f}" y="{bar_y}" width="{bar_w * ratio:.1f}" height="{bar_h}" rx="2" '
                f'fill="{C["blue"]}"/>'
                f'<text x="{bar_x + bar_w + 10:.1f}" y="{y}" xml:space="preserve" fill="{C["fg"]}">{esc(label_right)}</text>'
                f'</g>'
            )

        self._add(Row("bar", draw, total_px))

    def cursor(self):
        self._add(Row("cursor", lambda y, _id: "", 0))


# ─── content ────────────────────────────────────────────────────────
def populate(b, cf, lc):
    cfg = CONFIG

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
            (str(cf["rating"]), C["yellow"]),
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


# ─── render ─────────────────────────────────────────────────────────
def build_terminal(cf, lc):
    b = Builder()
    populate(b, cf, lc)
    rows = b.rows

    # 1. Y positions
    y = BODY_TOP
    for row in rows:
        if row.follows_gap:
            y += SECTION_GAP
        row.y = y
        y += LINE_H
    height = y + BODY_BOTTOM

    # 2. Typing schedule
    schedule = []  # (row, start, end) for non-cursor rows
    t = INITIAL_DELAY
    for row in rows:
        if row.kind == "cursor":
            continue
        if row.follows_gap:
            t += SECTION_PAUSE_EXTRA
        start = t
        dur = max(MIN_LINE_DUR, (row.px_width / CHAR_W) * CHAR_DUR)
        end = start + dur
        schedule.append((row, start, end))
        t = end + LINE_PAUSE

    typing_end = t
    cycle = typing_end + HOLD_AT_END

    # 3. ClipPath defs + clipped row content
    clip_defs = []
    body_parts = []
    for i, (row, start, end) in enumerate(schedule):
        clip_id = f"c{i}"
        anim_w = row.px_width + 6
        s_pct = start / cycle
        e_pct = end / cycle
        clip_defs.append(
            f'<clipPath id="{clip_id}">'
            f'<rect x="{PAD_X - 2}" y="{row.y - LINE_H + 4}" width="0" height="{LINE_H}">'
            f'<animate attributeName="width" '
            f'dur="{cycle:.3f}s" repeatCount="indefinite" '
            f'keyTimes="0;{s_pct:.4f};{e_pct:.4f};1" '
            f'values="0;0;{anim_w:.1f};{anim_w:.1f}"/>'
            f'</rect>'
            f'</clipPath>'
        )
        body_parts.append(row.draw_fn(row.y, clip_id))

    # 4. Cursor (appears after typing finishes; blinks while visible)
    cursor_row = next((r for r in rows if r.kind == "cursor"), None)
    cursor_svg = ""
    if cursor_row:
        cy = cursor_row.y
        appear_pct = typing_end / cycle
        eps = 0.0005
        cursor_svg = (
            f'<g opacity="0">'
            f'<animate attributeName="opacity" '
            f'dur="{cycle:.3f}s" repeatCount="indefinite" '
            f'keyTimes="0;{max(0.0001, appear_pct - eps):.4f};{appear_pct:.4f};1" '
            f'values="0;0;1;1"/>'
            f'<text x="{PAD_X}" y="{cy}" xml:space="preserve">'
            f'<tspan fill="{C["green"]}">❯</tspan>'
            f'</text>'
            f'<rect x="{PAD_X + 16}" y="{cy - 12}" width="8" height="14" fill="{C["fg_bright"]}">'
            f'<animate attributeName="opacity" values="1;0;1" dur="1.05s" repeatCount="indefinite"/>'
            f'</rect>'
            f'</g>'
        )

    # 5. Header
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
        f'<defs>'
        f'<clipPath id="r"><rect x="0" y="0" width="{WIDTH}" height="{height}" rx="10" ry="10"/></clipPath>'
        f'{"".join(clip_defs)}'
        f'</defs>'
        f'<g clip-path="url(#r)">'
        f'<rect width="{WIDTH}" height="{height}" fill="{C["bg"]}"/>'
        f'{header}'
        f'<g>{"".join(body_parts)}</g>'
        f'{cursor_svg}'
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
