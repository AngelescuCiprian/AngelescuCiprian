"""Generate the SVG assets for the GitHub profile README.

    python scripts/build_assets.py            # rebuild SVGs from scripts/stats.json
    python scripts/build_assets.py --refresh  # re-read stats from the GitHub API first (needs `gh` logged in)

Fonts (OFL) are downloaded once into scripts/.fonts, subset to the glyphs each SVG
uses and embedded as WOFF2, so every visitor sees the same type.
"""
from __future__ import annotations

import base64
import io
import json
import subprocess
import sys
import textwrap
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONT_DIR = Path(__file__).resolve().parent / ".fonts"
STATS_FILE = Path(__file__).resolve().parent / "stats.json"
USER = "AngelescuCiprian"

# ── tokens ───────────────────────────────────────────────────────────────────
# Surface and border match the AI-Atlas badge so the two read as one set.
INK = "#0E141B"
LINE = "#2D3B47"
DOTS = "#18222C"
TEXT = "#E6EBF0"
MUTED = "#8A97A6"
DIM = "#4A5764"
AMBER = "#F0B43C"  # the human gate, used nowhere else
MINT = "#6FD3A0"   # verified, used nowhere else
# Language bar: categorical slots validated for this dark surface (dataviz validator, all checks pass).
LANG_COLORS = ["#3987E5", "#199E70", "#9085E9", "#D55181"]
OTHER_COLOR = "#4A5764"
EXCLUDED_LANGS = {"HTML", "CSS", "Jupyter Notebook"}  # generated dashboards would swamp the bar

FONT_SOURCES = {
    "serif": ("InstrumentSerif-Regular.ttf",
              "https://github.com/google/fonts/raw/main/ofl/instrumentserif/InstrumentSerif-Regular.ttf"),
    "serif-italic": ("InstrumentSerif-Italic.ttf",
                     "https://github.com/google/fonts/raw/main/ofl/instrumentserif/InstrumentSerif-Italic.ttf"),
    "mono-var": ("JetBrainsMono.ttf",
                 "https://github.com/google/fonts/raw/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf"),
}
MONO_ADVANCE = 0.6  # JetBrains Mono advance width, in em


# ── fonts ────────────────────────────────────────────────────────────────────
def _download(name: str) -> Path:
    fname, url = FONT_SOURCES[name]
    path = FONT_DIR / fname
    if not path.exists():
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, path)
    return path


def _load_fonts() -> dict[str, TTFont]:
    fonts = {
        "serif": TTFont(_download("serif")),
        "serif-italic": TTFont(_download("serif-italic")),
    }
    var = _download("mono-var")
    fonts["mono"] = instancer.instantiateVariableFont(TTFont(var), {"wght": 400})
    fonts["mono-bold"] = instancer.instantiateVariableFont(TTFont(var), {"wght": 700})
    return fonts


FONTS = _load_fonts()
FAMILY = {"serif": "IS", "serif-italic": "ISI", "mono": "JBM", "mono-bold": "JBMB"}


def text_width(s: str, font: str, size: float) -> float:
    if font.startswith("mono"):
        return len(s) * MONO_ADVANCE * size
    f = FONTS[font]
    cmap, hmtx, upm = f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm
    return sum(hmtx[cmap.get(ord(c), cmap[32])][0] for c in s) * size / upm


def font_face(font: str, chars: set[str]) -> str:
    f = FONTS[font]
    cmap = f.getBestCmap()
    missing = sorted(c for c in chars if ord(c) not in cmap and not c.isspace())
    if missing:
        raise SystemExit(f"font {font} has no glyph for: {''.join(missing)}")
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["kern", "liga"]
    opts.name_IDs = []
    opts.notdef_outline = True
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=[ord(c) for c in chars | {" "}])
    buf = io.BytesIO()
    f.save(buf)
    buf.seek(0)
    clone = TTFont(buf)
    sub.subset(clone)
    out = io.BytesIO()
    clone.flavor = "woff2"
    clone.save(out)
    data = base64.b64encode(out.getvalue()).decode()
    return f"@font-face{{font-family:{FAMILY[font]};src:url(data:font/woff2;base64,{data}) format('woff2')}}"


# ── svg builder ──────────────────────────────────────────────────────────────
class Svg:
    def __init__(self, w: int, h: int, title: str, desc: str):
        self.w, self.h, self.title, self.desc = w, h, title, desc
        self.parts: list[str] = []
        self.css: list[str] = []
        self.used: dict[str, set[str]] = {k: set() for k in FAMILY}

    def add(self, s: str) -> None:
        self.parts.append(s)

    def text(self, x, y, s, font="mono", size=13, fill=TEXT, anchor="start", cls="", extra=""):
        self.used[font].update(s)
        c = f' class="{cls}"' if cls else ""
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FAMILY[font]}" font-size="{size}" '
                 f'fill="{fill}"{a}{c}{extra}>{escape(s)}</text>')

    def frame(self, radius=14):
        self.add(f'<rect width="{self.w}" height="{self.h}" rx="{radius}" fill="{INK}"/>')
        self.add(f'<rect x="0.5" y="0.5" width="{self.w - 1}" height="{self.h - 1}" rx="{radius - .5}" '
                 f'fill="none" stroke="{LINE}"/>')

    def render(self) -> str:
        faces = "".join(font_face(k, v) for k, v in self.used.items() if v)
        style = faces + "".join(self.css)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}" role="img" aria-labelledby="t d">'
                f'<title id="t">{escape(self.title)}</title><desc id="d">{escape(self.desc)}</desc>'
                f'<style>{style}</style>{"".join(self.parts)}</svg>')

    def save(self, name: str) -> None:
        ASSETS.mkdir(parents=True, exist_ok=True)
        path = ASSETS / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(), encoding="utf-8")
        print(f"  {path.relative_to(ROOT)}  {path.stat().st_size / 1024:.0f} KB")


def wrap(s: str, size: float, width: float) -> list[str]:
    return textwrap.wrap(s, int(width // (size * MONO_ADVANCE)), break_on_hyphens=False)


# ── header ───────────────────────────────────────────────────────────────────
STEPS = [
    ("sync", "pull the current state of ~10k products"),
    ("validate", "check every row before touching anything"),
    ("plan", "write a fixed plan and a report a person can read"),
    ("approve", "wait: a human reads the plan and confirms it"),
    ("apply", "write only what was approved, resumable"),
    ("verify", "re-read the source to prove every change landed"),
]
STARTS = [0.4, 1.9, 3.4, 4.9, 8.2, 9.7]  # seconds; the human step holds longest
CYCLE, HOLD_END, RESET = 14.0, 13.2, 13.8


def pct(t: float) -> str:
    return f"{100 * t / CYCLE:.2f}%"


def build_header() -> None:
    w, h = 960, 400
    s = Svg(w, h, "Angelescu Ciprian — AI automation, business intelligence, web development",
            "An automation pipeline animates across the header: sync, validate, plan, a human approves, "
            "apply, verify. Nothing is written until a person approves the plan.")
    s.add('<defs><pattern id="g" width="24" height="24" patternUnits="userSpaceOnUse">'
          f'<circle cx="2" cy="2" r="1" fill="{DOTS}"/></pattern>'
          '<clipPath id="c"><rect width="960" height="400" rx="16"/></clipPath></defs>')
    s.add(f'<rect width="{w}" height="{h}" rx="16" fill="{INK}"/>')
    s.add(f'<rect width="{w}" height="{h}" fill="url(#g)" clip-path="url(#c)"/>')
    s.add(f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="15.5" fill="none" stroke="{LINE}"/>')

    s.text(48, 62, "angelescu-ciprian  ·  bucharest, ro", size=13, fill=MUTED)
    s.text(44, 152, "Angelescu Ciprian", font="serif-italic", size=86)
    s.text(48, 198, "AI automation  ·  Business intelligence  ·  Web development", size=15, fill=TEXT)
    s.add(f'<line x1="48" y1="244" x2="912" y2="244" stroke="{LINE}"/>')

    y, x0, x1 = 298, 76, 884
    xs = [x0 + i * (x1 - x0) / (len(STEPS) - 1) for i in range(len(STEPS))]
    length = x1 - x0

    # track + progress line
    s.add(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{LINE}" stroke-width="2"/>')
    kf = [f"0%{{stroke-dashoffset:{length};opacity:1}}"]
    for i in range(1, len(STEPS)):
        kf.append(f"{pct(STARTS[i] - 0.6)}{{stroke-dashoffset:{length - (xs[i - 1] - x0):.1f}}}")
        kf.append(f"{pct(STARTS[i])}{{stroke-dashoffset:{length - (xs[i] - x0):.1f}}}")
    kf.append(f"{pct(HOLD_END)}{{stroke-dashoffset:0;opacity:1}}")
    kf.append(f"{pct(RESET)}{{stroke-dashoffset:0;opacity:0}}")
    kf.append(f"100%{{stroke-dashoffset:{length};opacity:0}}")
    s.css.append(f"@keyframes pr{{{''.join(kf)}}}.pr{{animation:pr {CYCLE}s linear infinite both}}")
    s.add(f'<line class="pr" x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{MUTED}" stroke-width="2" '
          f'stroke-dasharray="{length}" stroke-dashoffset="0"/>')

    for i, ((name, caption), x, t0) in enumerate(zip(STEPS, xs, STARTS)):
        on = AMBER if name == "approve" else MINT if name == "verify" else TEXT
        nxt = STARTS[i + 1] if i + 1 < len(STEPS) else HOLD_END
        # node: base style is the finished state (what reduced-motion users see)
        s.css.append(
            f"@keyframes n{i}{{0%,{pct(max(t0 - 0.01, 0))}{{fill:{INK};stroke:{DIM}}}"
            f"{pct(t0)},{pct(HOLD_END)}{{fill:{on};stroke:{on}}}"
            f"{pct(RESET)},100%{{fill:{INK};stroke:{DIM}}}}}"
            f".n{i}{{animation:n{i} {CYCLE}s linear infinite both}}")
        s.css.append(
            f"@keyframes h{i}{{0%,{pct(max(t0 - 0.01, 0))}{{opacity:0}}{pct(t0 + 0.15)}{{opacity:.9}}"
            f"{pct(nxt - 0.1)}{{opacity:.9}}{pct(nxt + 0.2)},100%{{opacity:0}}}}"
            f".h{i}{{opacity:0;animation:h{i} {CYCLE}s linear infinite both}}")
        s.css.append(
            f"@keyframes l{i}{{0%,{pct(max(t0 - 0.01, 0))}{{fill:{MUTED}}}{pct(t0)},{pct(nxt)}{{fill:{on}}}"
            f"{pct(nxt + 0.3)},100%{{fill:{MUTED}}}}}"
            f".l{i}{{animation:l{i} {CYCLE}s linear infinite both}}")
        last = i == len(STEPS) - 1
        s.css.append(
            f"@keyframes c{i}{{0%,{pct(max(t0 - 0.01, 0))}{{opacity:0}}{pct(t0 + 0.2)}{{opacity:1}}"
            f"{pct(nxt - 0.15)}{{opacity:1}}{pct(nxt + 0.1)},100%{{opacity:0}}}}"
            f".c{i}{{opacity:{1 if last else 0};animation:c{i} {CYCLE}s linear infinite both}}")

        if name == "approve":
            r = 9
            pts = f"{x},{y - r} {x + r},{y} {x},{y + r} {x - r},{y}"
            s.add(f'<polygon class="h{i}" points="{x},{y - 17} {x + 17},{y} {x},{y + 17} {x - 17},{y}" '
                  f'fill="none" stroke="{on}" stroke-opacity=".45"/>')
            s.add(f'<polygon class="n{i}" points="{pts}" fill="{on}" stroke="{on}" stroke-width="2"/>')
            s.text(x, y - 26, "human", size=11, fill=AMBER, anchor="middle")
        else:
            s.add(f'<circle class="h{i}" cx="{x}" cy="{y}" r="14" fill="none" stroke="{on}" stroke-opacity=".45"/>')
            s.add(f'<circle class="n{i}" cx="{x}" cy="{y}" r="6.5" fill="{on}" stroke="{on}" stroke-width="2"/>')
        s.text(x, y + 34, name, size=13, fill=on if name in ("approve", "verify") else MUTED,
               anchor="middle", cls=f"l{i}")
        s.text(48, 372, f"›  {caption}", size=13, fill=MUTED, cls=f"c{i}")

    s.css.append("@media (prefers-reduced-motion:reduce){*{animation:none!important}}")
    s.save("header.svg")


# ── stats ────────────────────────────────────────────────────────────────────
def gh(*args: str, check: bool = True) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check).stdout


def refresh_stats() -> dict:
    repos = json.loads(gh("repo", "list", USER, "--limit", "300", "--json", "name,visibility"))
    repos = [r for r in repos if r["name"] != USER]
    langs, commits = Counter(), 0
    for r in repos:
        langs.update(json.loads(gh("api", f"repos/{USER}/{r['name']}/languages")))
        # an empty repository answers 409, which simply means zero commits
        out = gh("api", f"repos/{USER}/{r['name']}/commits?per_page=100&author={USER}",
                 "--paginate", "--jq", "length", check=False)
        commits += sum(int(n) for n in out.split() if n.isdigit())
    cal = json.loads(gh("api", "graphql", "-f", "query=query{viewer{contributionsCollection{"
                        "restrictedContributionsCount contributionCalendar{totalContributions}}}}"))
    cc = cal["data"]["viewer"]["contributionsCollection"]
    stats = {
        "date": date.today().isoformat(),
        "repos": len(repos),
        "private": sum(r["visibility"] == "PRIVATE" for r in repos),
        "contributions": cc["contributionCalendar"]["totalContributions"],
        "private_contributions": cc["restrictedContributionsCount"],
        "commits": commits,
        "languages": dict(langs.most_common()),
    }
    STATS_FILE.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def build_stats(st: dict) -> None:
    w, h = 720, 380
    langs = {k: v for k, v in st["languages"].items() if k not in EXCLUDED_LANGS}
    total = sum(langs.values())
    top = list(langs.items())[:len(LANG_COLORS)]
    rest = list(langs.items())[len(LANG_COLORS):]
    segs = [(k, v / total, c) for (k, v), c in zip(top, LANG_COLORS)]
    segs.append(("Other", sum(v for _, v in rest) / total, OTHER_COLOR))
    public = st["repos"] - st["private"]
    priv_share = round(100 * st["private_contributions"] / st["contributions"])
    when = date.fromisoformat(st["date"]).strftime("%-d %b %Y") if sys.platform != "win32" \
        else date.fromisoformat(st["date"]).strftime("%#d %b %Y")

    s = Svg(w, h, "GitHub activity, private repositories included",
            f"{st['repos']} repositories ({public} public, {st['private']} private); "
            f"{st['contributions']} contributions in the last 12 months, {priv_share}% in private repositories; "
            f"{st['commits']} commits authored. Code by language: "
            + ", ".join(f"{k} {round(100 * p)}%" for k, p, _ in segs) + ".")
    # Shown at half width beside the AI-Atlas badge, so type is set large.
    s.frame()
    s.text(32, 50, f"read back from the GitHub API · {when}", size=16, fill=MUTED)
    s.text(30, 102, "Public and private, together", font="serif", size=44)

    rows = [
        (st["repos"], "repositories", f"{public} public · {st['private']} private"),
        (st["contributions"], "contributions", f"{priv_share}% private · 12 months"),
        (st["commits"], "commits", "authored by me"),
    ]
    for j, (n, label, detail) in enumerate(rows):
        y = 158 + j * 42
        s.text(92, y, str(n), font="mono-bold", size=24, anchor="end")
        s.text(110, y, label, size=20)
        s.text(688, y, detail, size=16, fill=MUTED, anchor="end")
    s.add(f'<line x1="32" y1="268" x2="688" y2="268" stroke="{LINE}"/>')

    bx, by, bw, bh, gap = 32, 288, 656, 16, 2
    s.add(f'<clipPath id="bar"><rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="4"/></clipPath>')
    x = bx
    usable = bw - gap * (len(segs) - 1)
    parts = []
    for k, p, c in segs:
        sw = usable * p
        parts.append(f'<rect x="{x:.1f}" y="{by}" width="{sw:.1f}" height="{bh}" fill="{c}"/>')
        x += sw + gap
    s.add(f'<g clip-path="url(#bar)">{"".join(parts)}</g>')

    x, ly, size = bx, 340, 15
    for k, p, c in segs:
        label = f"{k} {round(100 * p)}%"
        s.add(f'<rect x="{x}" y="{ly - 12}" width="12" height="12" rx="2" fill="{c}"/>')
        s.text(x + 18, ly, label, size=size, fill=TEXT)
        x += 18 + text_width(label, "mono", size) + 16
    if x - 16 > bx + bw:
        raise SystemExit(f"stats legend overflows by {x - 16 - bx - bw:.0f}px")
    s.text(32, 364, "code only: HTML, CSS and notebooks left out", size=13, fill=MUTED)
    s.save("stats.svg")


# ── areas ────────────────────────────────────────────────────────────────────
AREAS = [
    ("AI agents",
     "Claude Code systems, agent skills and MCP servers: assistants that answer from real data "
     "and stay read-only unless a person says otherwise.",
     "Claude Code · MCP · Agent Skills · smolagents"),
    ("Business intelligence",
     "Power BI semantic models, DAX and SQL. Reports that refresh themselves, alerts on stale data, "
     "735 measures documented across five models.",
     "Power BI · DAX · SQL · Python · GitHub Actions"),
    ("Process automation",
     "Playwright bots, Electron apps and POS integrations. Bulk changes run behind a plan that a "
     "person reads and approves.",
     "Playwright · Electron · TypeScript · Node.js"),
    ("Web products",
     "Sites and apps for clients through my own B2B company, from booking systems to fast "
     "static sites with their own admin panels.",
     "Next.js · React · Supabase · Postgres · Astro · PHP"),
]
FOUNDATIONS = ("Foundations",
               "From university: algorithms in C and C++, x86 Assembly down to IEEE-754 addition, "
               "agent-based simulation in NetLogo, Bash, C#.",
               "C · C++ · Assembly · C# · NetLogo · Bash")


def build_areas() -> None:
    w, pad, size, lh = 960, 32, 13, 20
    col = w / 2

    def block(s, x, y, width, title, desc, tools):
        s.text(x, y + 40, title, font="serif", size=30)
        lines = wrap(desc, size, width)
        for k, line in enumerate(lines):
            s.text(x, y + 72 + k * lh, line, size=size, fill=TEXT)
        s.text(x, y + 72 + len(lines) * lh + 12, tools, size=12, fill=MUTED)
        return 72 + len(lines) * lh + 12 + 28

    probe = Svg(1, 1, "", "")
    cell_h = max(block(probe, 0, 0, col - 2 * pad, *a) for a in AREAS)
    found_h = block(probe, 0, 0, w - 2 * pad, *FOUNDATIONS)
    h = int(2 * cell_h + found_h)

    s = Svg(w, h, "What I build",
            " ".join(f"{t}: {d} Tools: {tl}." for t, d, tl in AREAS + [FOUNDATIONS]))
    s.frame()
    for i, area in enumerate(AREAS):
        cx, cy = (i % 2) * col, (i // 2) * cell_h
        block(s, cx + pad, cy, col - 2 * pad, *area)
    s.add(f'<line x1="{col}" y1="24" x2="{col}" y2="{2 * cell_h - 24}" stroke="{LINE}"/>')
    s.add(f'<line x1="{pad}" y1="{cell_h}" x2="{w - pad}" y2="{cell_h}" stroke="{LINE}"/>')
    s.add(f'<line x1="{pad}" y1="{2 * cell_h}" x2="{w - pad}" y2="{2 * cell_h}" stroke="{LINE}"/>')
    block(s, pad, 2 * cell_h, w - 2 * pad, *FOUNDATIONS)
    s.save("areas.svg")


# ── project cards ────────────────────────────────────────────────────────────
CARDS = [
    # file, eyebrow, meta, title, description, stack
    ("pos-sync", "production · citygrill", "private",
     "POS price & allergen sync",
     "Updates prices, allergens and nutrition for ~10k products from Excel. Nothing is "
     "written before a person approves the plan; every write is re-read.",
     "TypeScript · Node 24 · REST · Excel"),
    ("bi-assistant", "production · citygrill", "private",
     "BI assistant in plain Romanian",
     "Ask about sales or KPIs and get answers from five Power BI models and the warehouse. "
     "Read-only by design: an allow-list guard with 33 offline tests.",
     "Claude Code · Python · DAX · SQL"),
    ("weekly-report", "production · citygrill", "private",
     "Weekly operations report",
     "A shared sheet with one tab per location becomes an interactive dashboard, emailed every "
     "Monday for 22 locations. A bad tab is quarantined, not shipped.",
     "Python · GitHub Actions · HTML/JS"),
    ("stale-data", "production · citygrill", "private",
     "Stale-data alerts",
     "Checks daily that the main performance report shows yesterday's data, in Romanian "
     "time. Silent when all is well; the subject says how bad it is.",
     "Python · GitHub Actions · Power BI REST"),
    ("events-dashboard", "production · citygrill", "private",
     "Events dashboard on demand",
     "Rebuilds from Power BI in about 20 seconds, from any device. Reconciled row by row "
     "against the SQL source before anyone relied on it.",
     "Python · DAX · MSAL · GitHub Actions"),
    ("export-app", "production · citygrill", "private",
     "Inventory export app",
     "A desktop app that runs the monthly import and export for every location, made for a "
     "non-technical colleague. Picks up where it stopped after a crash.",
     "Electron · Playwright · TypeScript"),
    ("aios", "open source", "1 star",
     "AIOS for Claude Code",
     "A local-first AI operating system for Claude Code: persistent memory, skills, sub-agents "
     "and a visual dashboard. Written in Romanian.",
     "TypeScript · Python · Claude Code"),
    ("claude-skills", "open source", "117 skills",
     "Claude skills collection",
     "Curated skills for Claude Code and Junie: AI media, Office documents, browser "
     "automation, deploys. Installs pinned by a lock file.",
     "Agent Skills · Shell · Python"),
    ("library-bot", "open source", "3 stars",
     "Library cataloguing bot",
     "Registers digitised periodicals in the Romanian Academy Library catalogue, with "
     "covers and PDFs. Progress goes back to the sheet, so runs resume.",
     "Playwright · TypeScript · Excel"),
    ("menu-scraper", "open source", "public",
     "Competitor menu scraper",
     "Collects competitors' menu prices, category by category, into a dataset that can be "
     "compared side by side with our own menu.",
     "Python · Playwright"),
    ("salon-booking", "client work", "private",
     "Salon booking app",
     "Online booking for a salon in Găești, plus an admin panel for the stylists. A Postgres "
     "exclusion constraint makes double booking impossible.",
     "Next.js 16 · Supabase · Tailwind · Vercel"),
    ("bsk-site", "client work", "bskmetaconstruct.ro",
     "Construction company site",
     "A fast static site for a steel-structures builder, with a PHP admin for the project "
     "gallery. Lighthouse 98–100 on mobile.",
     "Astro · Tailwind · PHP"),
]


def build_cards() -> None:
    w, pad, size, lh = 460, 26, 13, 20
    for c in CARDS:
        if len(wrap(c[4], size, w - 2 * pad)) > 3:
            raise SystemExit(f"card {c[0]}: description runs past 3 lines")
    h = 108 + 2 * lh + 58
    for fname, eyebrow, meta, title, desc, stack in CARDS:
        s = Svg(w, h, title, f"{eyebrow}. {desc} Stack: {stack}.")
        s.frame()
        s.text(pad, 36, eyebrow, size=11.5, fill=MUTED)
        s.text(w - pad, 36, meta, size=11.5, fill=MUTED, anchor="end")
        s.text(pad - 1, 78, title, font="serif", size=28)
        for k, line in enumerate(wrap(desc, size, w - 2 * pad)):
            s.text(pad, 108 + k * lh, line, size=size)
        s.text(pad, h - 24, stack, size=11.5, fill=MUTED)
        s.save(f"cards/{fname}.svg")


def main() -> None:
    stats = refresh_stats() if "--refresh" in sys.argv else json.loads(STATS_FILE.read_text("utf-8"))
    print("building assets:")
    build_header()
    build_stats(stats)
    build_areas()
    build_cards()


if __name__ == "__main__":
    main()
