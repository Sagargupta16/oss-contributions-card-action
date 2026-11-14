"""The flat style (style: flat): the open-source cards of the profile README this action comes from.

Ported from the profile's design kit (brand/Sagargupta16/scripts/kit.py: palette,
type, the page clock, poster-safe entrances, chips) and its open-source cards
(scripts/cards/oss.py), so a card made with style: flat looks like the one on
the profile. Two cards, each with a 320px phone twin:

- summary: four tiles (merged upstream, repositories with merges, their combined
  stars, open pull requests) over the merged ledger, a git-log rail of the
  newest six merges. Five rows are in view and the ledger steps up a row every
  4 s, so six rows close on 24 s; the poster is the newest five, and the newest
  merge carries the green merged mark, pulsing. On each step the top row fades
  out before the rows move and the arriving row fades in after, so no row is
  ever drawn half cut by the window. ALSO MERGED INTO names the repositories the
  ledger does not show, the most starred first, and the rest of the pull
  requests fold into "+N more pull requests on GitHub".
- review: the repositories with open pull requests as chips with their counts,
  the most starred first, under the one amber mark (IN REVIEW).

The summary card carries the merged list, so this style has no merged card.

Cards are flat: one fill and one hairline border, no gradient, glow or shine.
Green marks the newest merge only and amber the work in review only. Every loop
lasts 2, 3, 4, 6, 12 or 24 s, and every entrance is poster-safe: an element's
own attributes hold its finished frame and its animation holds the start value
from 0 s until its turn, so a still render shows the whole card.

render() is pure: it reads no files, no clock and no network. Stdlib only.
"""

from __future__ import annotations

import re
import unicodedata
from html import escape
from itertools import pairwise

# ---------------------------------------------------------------- palette
# Warm near-black, one blue family, green only for the newest merge, amber only
# for work waiting on review.
BG = "#0b1012"  # every card's surface
CARD = "#0f171c"  # panels and tiles inside a card
BLUE_EDGE = "#3b82f6"  # outlines on a blue tint (4.3:1 and up)
BLUE_LIGHT = "#60a5fa"  # labels, links, the moving highlight
SKY = "#38bdf8"  # the star mark
BLUE_TINT = "rgba(37,99,235,0.14)"  # the fill behind an emphasised tile
GREEN = "#22c55e"
AMBER = "#f59e0b"
INK = "#f3f4f6"  # titles and values
META = "rgba(255,255,255,0.62)"  # captions; 4.5:1 and up on BG and CARD
HAIR = "rgba(255,255,255,0.09)"  # a card's border
HAIR_STRONG = "rgba(255,255,255,0.14)"  # a tile's border, the rail
HAIR_FILL = "rgba(255,255,255,0.03)"
COUNTER = "rgba(255,255,255,0.10)"  # GitHub's grey counter pill

# ---------------------------------------------------------------- type
MONO = "'JetBrains Mono','SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"
SANS = "'Segoe UI',Inter,-apple-system,BlinkMacSystemFont,Helvetica,Arial,sans-serif"
MICRO = (
    10.5  # the smallest desktop label: 10px once an 840px card fills a README column
)
MICRO_PHONE = 11.5  # the smallest label on a 320px card
TRACK = 1.2  # letter-spacing of a mono micro-label
RADIUS = 14

# ---------------------------------------------------------------- clock
# One page clock. Every loop lasts one of CLOCK's lengths, so cards that sit
# next to each other realign and nothing drifts. Entrances run once and are
# over within about 1.6 s.
T = 12.0
CLOCK = (2, 3, 4, 6, 12, 24)
ENTER = 0.4
STAGGER = 0.08
EASE = "0.16 1 0.3 1"  # ease-out for entrances
SMOOTH = "0.4 0 0.2 1"  # ease in and out, for a move that travels and stops
SVG_CLOSE = "</svg>"

# ---------------------------------------------------------------- layout
WIDTH, PHONE = 840, 320
PAD, PHONE_PAD = 24, 16
# Both widths show this many ledger rows and count the rest into one "+N more"
# line, so the cards stop growing with every merge and the two widths agree.
MERGED_SHOWN = 6
WINDOW = 5  # desktop ledger rows in view; the poster is the newest five
STEP = 4.0  # the ledger moves on a row this often: 6 rows x 4 s = 24 s
ROLL = 0.4  # how long one move takes
# a row crossing the window's edge fades over this long: the leaving one before
# the move, the arriving one after it, so the step ends on the beat
FADE = 0.3
PITCH = 40  # one desktop ledger row
INSET = 10  # the first ledger row's top, down from the panel's
ALSO_SHOWN = 3  # repositories ALSO MERGED INTO names at both widths before "+N more"
ALSO_GAP = 20  # between two of those names
FOOT = 24  # one line under the desktop ledger's rule
REVIEW_ROWS = (
    3  # desktop chip rows before the rest of the repositories fold into a count
)
PHONE_REVIEW = 6  # repositories listed on the phone review card
PHONE_TITLE = 3  # lines a pull request title may take on the phone before it is cut
ARROW = chr(0x2192)  # a right arrow, as a code point so this file stays plain ASCII

STAR = "M5 0.6 6.4 3.5 9.6 3.9 7.3 6.1 7.9 9.3 5 7.8 2.1 9.3 2.7 6.1 0.4 3.9 3.6 3.5Z"  # 10 x 10
TICK = "M-3.4 0.2l2.3 2.3 4.5-4.8"  # an ok tick centred on 0 0, 8 wide
# 16 x 16 line glyphs for the tiles, drawn like GitHub's own marks
GLYPHS = {
    "merge": '<circle cx="4" cy="3.5" r="2"/><circle cx="4" cy="12.5" r="2"/><circle cx="12" cy="8" r="2"/>'
    '<path d="M4 5.5v5M4 5.5c0 2.5 2.5 2.5 6 2.5"/>',
    "repo": '<path d="M4.5 2h8v12h-8A1.5 1.5 0 0 1 3 12.5v-9A1.5 1.5 0 0 1 4.5 2zM3 11.5h9.5"/>',
    "star": '<path d="M8 1.4 10.1 5.75 14.9 6.35 11.45 9.65 12.35 14.45 8 12.2 3.65 14.45 4.55 9.65 1.1 6.35 5.9 5.75Z"/>',
    "pr": '<circle cx="4" cy="3.5" r="2"/><circle cx="4" cy="12.5" r="2"/><circle cx="12" cy="12.5" r="2"/>'
    '<path d="M4 5.5v5M12 10.5V7a2.5 2.5 0 0 0-2.5-2.5H7M8.6 2.9 7 4.5l1.6 1.6"/>',
}


# ---------------------------------------------------------------- text metrics
def _advance(character: str) -> float:
    if unicodedata.combining(character):
        return 0
    if unicodedata.east_asian_width(character) in {"W", "F"}:
        return 1.05
    if character in "W@%M":
        return 1
    if character in "ilI.,:;'!|`":
        return 0.34
    if character in " fjrt()[]":
        return 0.44
    return 0.7 if character.isupper() else 0.58


def text_width(
    text: str, size: float = 15, mono: bool = False, tracking: float = 1
) -> float:
    """Measure text conservatively: sans glyph advances, or monospace plus its tracking."""
    if mono:
        return len(text) * (size * 0.6 + tracking)
    return sum(_advance(character) for character in text) * size


def wrap_text(
    text: str, width: float, size: float = 15, mono: bool = False, tracking: float = 1
) -> list[str]:
    """Wrap words to a pixel width, splitting long tokens without dropping any content."""
    lines, current = [], ""
    for word in str(text).split():
        candidate = f"{current} {word}" if current else word
        if text_width(candidate, size, mono, tracking) <= width:
            current = candidate
            continue
        if current:
            # A token wider than the line splits anyway, so it starts on this
            # line. So does one that would nearly fill the next line and has a
            # "/", "-", "_" or "." to break at, when the words before it would
            # otherwise sit alone on a short line.
            token = text_width(word, size, mono, tracking)
            short_line = text_width(current, size, mono, tracking) < width / 2
            breakable = token > width * 0.75 and re.search("[/_.-].", word)
            if token > width or (short_line and breakable):
                current += " "
            else:
                lines.append(current)
                current = ""
        # a token too long for a line breaks after "/", "-", "_" or "." first,
        # and only splits between letters where no separator fits
        for piece in re.findall(r"[^/\-_.]+[/\-_.]*|[/\-_.]+", word):
            if (
                current.strip()
                and text_width(current + piece, size, mono, tracking) > width
            ):
                lines.append(current.rstrip())
                current = ""
            for character in piece:
                if (
                    current.strip()
                    and text_width(current + character, size, mono, tracking) > width
                ):
                    lines.append(current.rstrip())
                    current = ""
                current += character
    if current:
        lines.append(current)
    return lines


def balance(lines: list[str]) -> list[str]:
    """Move one word down when the last line would hold a single short word."""
    if len(lines) < 2 or " " in lines[-1] or len(lines[-1]) > 12:
        return lines
    head = lines[-2].rsplit(" ", 1)
    if len(head) < 2:
        return lines
    return [*lines[:-2], head[0], f"{head[1]} {lines[-1]}"]


def compact(number: float) -> str:
    """Shorten a count, rounding down so a card never claims more than there is: 941, 1.2K, 24K, 1.3M."""
    for limit, unit in ((1_000_000, "M"), (1_000, "K")):
        if number >= limit:
            if number >= limit * 10:
                return f"{int(number // limit)}{unit}"
            tenths = int(number * 10 // limit)
            return f"{tenths // 10}.{tenths % 10}".removesuffix(".0") + unit
    return f"{int(number):,}"


# ---------------------------------------------------------------- chrome
def svg_open(w: float, h: float, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:g}" height="{h:g}" viewBox="0 0 {w:g} {h:g}" '
        f'role="img" aria-label="{escape(label)}">'
    )


def _css() -> str:
    """The shared text classes: m micro-label, c code or data, s strong, b body, n numeral."""
    return (
        "<style>"
        f".m{{font-family:{MONO};font-weight:700;letter-spacing:{TRACK}px}}"
        f".c{{font-family:{MONO};font-weight:500}}"
        f".s{{font-family:{SANS};font-weight:600}}"
        f".b{{font-family:{SANS};font-weight:500}}"
        f".n{{font-family:{SANS};font-weight:800;font-variant-numeric:tabular-nums}}"
        "</style>"
    )


def card_open(w: float, h: float, label: str, defs: str = "") -> str:
    """Open a card: the svg root, the shared classes, a clip for its rounded corners and the flat surface."""
    return (
        svg_open(w, h, label)
        + _css()
        + f'<defs><clipPath id="card"><rect x="1" y="1" width="{w - 2:g}" height="{h - 2:g}" rx="{RADIUS - 1}"/></clipPath>{defs}</defs>'
        + f'<rect x="0.5" y="0.5" width="{w - 1:g}" height="{h - 1:g}" rx="{RADIUS}" fill="{BG}" stroke="{HAIR}"/>'
    )


def text(
    x: float,
    y: float,
    content: str,
    size: float,
    fill: str = INK,
    cls: str = "b",
    anchor: str = "",
    extra: str = "",
) -> str:
    align = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text class="{cls}" x="{x:g}" y="{y:g}" font-size="{size:g}" fill="{fill}"{align}{extra}>{escape(str(content))}</text>'


def eyebrow(
    x: float, y: float, label: str, fill: str = BLUE_LIGHT, anchor: str = ""
) -> str:
    """The mono micro-label a card opens with."""
    return text(x, y, label.upper(), MICRO, fill, "m", anchor)


# ---------------------------------------------------------------- motion
def keys(points: list[tuple[float, str]], dur: float = T) -> tuple[str, str]:
    """(values, keyTimes) for (seconds, value) points that run from 0 to dur."""
    values = ";".join(value for _, value in points)
    times = ";".join(f"{round(second / dur, 4):g}" for second, _ in points)
    return values, times


def held(begin: float, dur: float) -> str:
    """Timing that runs from 0 s and holds the start value until begin.

    The element's own attributes hold the finished frame, so a still render
    (link preview, print, a viewer without SMIL) shows the whole card, and a
    browser never flashes the item before its turn.
    """
    total = begin + dur
    return (
        f'keyTimes="0;{begin / total:.3f};1" dur="{total:.2f}s" fill="freeze"'
        f' calcMode="spline" keySplines="0 0 1 1;{EASE}"'
    )


def group(at: float, body: str, shift: str = "0 8") -> str:
    """Wrap a block so it fades in and rises 8px at `at`, poster-safe."""
    times = held(at, ENTER)
    return (
        f'<g><animate attributeName="opacity" values="0;0;1" {times}/>'
        f'<animateTransform attributeName="transform" type="translate" values="{shift};{shift};0 0" {times}/>'
        f"{body}</g>"
    )


def loop(attribute: str, values: str, key_times: str, dur: float = T) -> str:
    """A repeating animation on the page clock; dur must be one of CLOCK."""
    return (
        f'<animate attributeName="{attribute}" values="{values}" keyTimes="{key_times}" '
        f'dur="{dur:g}s" repeatCount="indefinite"/>'
    )


def live_dot(cx: float, cy: float, color: str = GREEN, r: float = 4) -> str:
    """A status point: a ring that widens and fades every 2 s under a steady dot."""
    return (
        f'<circle cx="{cx:g}" cy="{cy:g}" r="{r:g}" fill="none" stroke="{color}" stroke-width="1.5">'
        f'<animate attributeName="r" values="{r:g};{r + 7:g}" dur="2s" repeatCount="indefinite"/>'
        '<animate attributeName="opacity" values="0.9;0" dur="2s" repeatCount="indefinite"/></circle>'
        f'<circle cx="{cx:g}" cy="{cy:g}" r="{r:g}" fill="{color}"/>'
    )


def chip_width(
    label: str, size: float = MICRO, pad: float = 10, tracking: float = TRACK
) -> float:
    return text_width(label, size, True, tracking) + pad * 2 - tracking


def chip(
    x: float,
    y: float,
    label: str,
    color: str = BLUE_LIGHT,
    size: float = MICRO,
    height: float = 22,
    pad: float = 10,
) -> str:
    """A mono pill, its label centred so a measuring error shows as even padding."""
    width = chip_width(label, size, pad)
    return (
        f'<rect x="{x:g}" y="{y:g}" width="{width:.1f}" height="{height:g}" rx="{height / 2:g}" fill="{HAIR_FILL}" stroke="{HAIR_STRONG}"/>'
        + text(
            x + width / 2,
            y + height / 2 + size * 0.36,
            label,
            size,
            color,
            "m",
            "middle",
        )
    )


# ---------------------------------------------------------------- shared facts
# The cards read one dictionary, built by the action from its search results:
# merged (newest first) and open, each a list of {repo, title, number, date,
# stars}, and the counts merged_count, open_count, repos and combined_stars.
def _count(number: int, one: str, many: str = "") -> str:
    return f"{number} {one if number == 1 else many or one + 's'}"


def _by_stars(rows: list[dict]) -> list[tuple[str, int]]:
    """(repository, stars) for each repository once, the most starred first; a tie keeps the rows' order."""
    stars: dict[str, int] = {}
    for row in rows:
        stars[row["repo"]] = max(stars.get(row["repo"], 0), row.get("stars") or 0)
    return sorted(stars.items(), key=lambda item: -item[1])


def _also(oss: dict, shown: int) -> list[tuple[str, int]]:
    """The repositories with a merge that the ledger's rows do not show, the most starred first."""
    listed = {row["repo"] for row in oss["merged"][:shown]}
    return [item for item in _by_stars(oss["merged"]) if item[0] not in listed]


def _reach(stars: int) -> str:
    """Round the combined stars down, so the tile never claims more than the live count: 238K+, 1.2M+."""
    return compact(stars) + "+" if stars >= 1000 else str(stars)


def _tiles(oss: dict) -> list[tuple[str, str, str]]:
    """(value, label, glyph) for the four tiles, in the order both widths draw them."""
    return [
        (str(oss["merged_count"]), "MERGED UPSTREAM", "merge"),
        (str(oss["repos"]), "REPOS WITH MERGES", "repo"),
        (_reach(oss["combined_stars"]), "COMBINED STARS", "star"),
        (str(oss["open_count"]), "OPEN PRS", "pr"),
    ]


def _hidden(oss: dict, shown: int) -> int:
    """The merged pull requests past the ledger's rows."""
    return max(0, len(oss["merged"]) - shown)


def _prs(count: int) -> str:
    return f"{count} more pull request{'' if count == 1 else 's'}"


def _more(hidden: int) -> str:
    """Pull requests, said in full: after a list of repositories a bare "+6 more" reads as six more repositories."""
    return f"+{_prs(hidden)} on GitHub {ARROW}"


def _first_merge(oss: dict) -> str:
    """The eyebrow's date: the oldest merge, which no row shows (the newest is the ledger's first row)."""
    dates = [row["date"] for row in oss["merged"] if row.get("date")]
    return f"FIRST MERGE {min(dates)}" if dates else "MERGED UPSTREAM"


def _in_review(rows: list[dict]) -> list[tuple[str, int, int]]:
    """(repository, open pull requests, stars) for each repository, the most starred first."""
    counts: dict[str, int] = {}
    stars: dict[str, int] = {}
    for row in rows:
        counts[row["repo"]] = counts.get(row["repo"], 0) + 1
        stars[row["repo"]] = max(stars.get(row["repo"], 0), row.get("stars") or 0)
    ranked = sorted(counts, key=lambda repo: (-stars[repo], -counts[repo], repo))
    return [(repo, counts[repo], stars[repo]) for repo in ranked]


def _review_head(oss: dict, repos: int) -> str:
    """The review card's eyebrow: where the open pull requests are. Their count is the
    summary card's fourth tile, so the eyebrow does not say it again."""
    if not repos:
        return "NO OPEN PRS"
    return "1 REPOSITORY" if repos == 1 else f"{repos} REPOSITORIES"


# ---------------------------------------------------------------- labels
def _summary_label(oss: dict, shown: int) -> str:
    parts = [
        (
            f"Open source: {_count(oss['merged_count'], 'pull request')} merged upstream into "
            f"{_count(oss['repos'], 'repository', 'repositories')} with {_reach(oss['combined_stars'])} "
            f"combined stars, and {_count(oss['open_count'], 'pull request')} open."
        )
    ]
    if oss["merged"]:
        # every repository with a merge, not only the ledger's: the alt text is
        # the one place a reader without the image learns where the work landed
        names = ", ".join(repo for repo, _ in _by_stars(oss["merged"]))
        parts.append(f"Merged into, most starred first: {names}.")
        hidden = _hidden(oss, shown)
        if hidden:
            listed = len(oss["merged"][:shown])
            parts.append(
                f"The {listed} newest merges are listed, with {_prs(hidden)} on GitHub."
            )
    return " ".join(parts)


def _review_label(oss: dict) -> str:
    repos = _in_review(oss["open"])
    if not repos:
        return "No pull requests open upstream."
    listed = ", ".join(
        f"{repo} ({count})" if count > 1 else repo for repo, count, _ in repos
    )
    return f"{_count(oss['open_count'], 'pull request')} in review upstream: {listed}."


# ---------------------------------------------------------------- drawing helpers
def _width(content: str, size: float, cls: str = "b") -> float:
    """The width measured for a label of this class: mono for c and m, tracked for m."""
    if cls == "m":
        return text_width(content, size, True, TRACK) - TRACK
    if cls == "c":
        return text_width(content, size, True, 0)
    return text_width(content, size)


def _mono(
    x: float,
    y: float,
    content: str,
    size: float,
    fill: str,
    cls: str = "c",
    anchor: str = "",
) -> str:
    """A mono label pinned to the width measured for it.

    Whatever sits after it (a counter, a star) is placed by that measure, so
    textLength holds the gap even where the viewer's mono font is narrower.
    """
    pin = f' textLength="{_width(content, size, cls):.1f}" lengthAdjust="spacing"'
    return text(x, y, content, size, fill, cls, anchor, pin if content else "")


def _fit(content: str, room: float, size: float, cls: str = "b") -> str:
    """The text whole when it fits `room`, else cut at a word (or a character) and closed with three dots."""
    if _width(content, size, cls) <= room:
        return content
    cut = content
    while " " in cut and _width(cut + "...", size, cls) > room:
        cut = cut.rsplit(" ", 1)[0]
    while cut and _width(cut + "...", size, cls) > room:
        cut = cut[:-1]
    return cut.rstrip(" ,;:.") + "..."


def _lines(
    content: str, room: float, size: float, cap: int, cls: str = "b"
) -> list[str]:
    """Wrap to `room`; past `cap` lines the last kept line ends in three dots."""
    mono = cls != "b"
    lines = wrap_text(content, room, size, mono, 0)
    if len(lines) <= cap:
        return lines if mono else balance(lines)
    rest = ("" if mono else " ").join(lines[cap - 1 :])
    return [*lines[: cap - 1], _fit(rest, room, size, cls)]


def _glyph(name: str, x: float, y: float, clear: float = 0) -> str:
    """A tile's glyph with its top left at x, y; left out when the numeral reaches `clear` past x."""
    if clear > x:
        return ""
    return (
        f'<g transform="translate({x:g} {y:g})" fill="none" stroke="{BLUE_LIGHT}" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round">{GLYPHS[name]}</g>'
    )


def _star_width(stars: int, size: float) -> float:
    return 14 + _width(compact(stars), size, "c")


def _star(x: float, baseline: float, stars: int, size: float, fill: str) -> str:
    """A star and the compact count after it, from x on the text baseline."""
    top = baseline - size * 0.36 - 5
    return (
        f'<path d="{STAR}" fill="{SKY}" transform="translate({x:g} {top:.1f})"/>'
        + _mono(x + 14, baseline, compact(stars), size, fill)
    )


def _counter(x: float, mid: float, count: int, size: float) -> tuple[str, float]:
    """GitHub's counter: the number in a grey pill from x. Returns (svg, width)."""
    pill = _width(str(count), size, "c") + 12
    return (
        f'<rect x="{x:g}" y="{mid - 9:g}" width="{pill:g}" height="18" rx="9" fill="{COUNTER}"/>'
        + text(x + pill / 2, mid + size * 0.36, str(count), size, INK, "c", "middle")
    ), pill


def _node(cx: float, cy: float, newest: bool) -> str:
    """A merge on the rail: hollow, or for the newest the green disc with a tick, pulsing every 2 s."""
    if not newest:
        return f'<circle cx="{cx:g}" cy="{cy:g}" r="4.5" fill="none" stroke="{BLUE_LIGHT}" stroke-width="1.5"/>'
    return live_dot(cx, cy, GREEN, 6.5) + (
        f'<path transform="translate({cx:g} {cy:g}) scale(0.87)" d="{TICK}" fill="none" '
        f'stroke="{BG}" stroke-width="2.07" stroke-linecap="round" stroke-linejoin="round"/>'
    )


def _waiting(cx: float, cy: float) -> str:
    """A quiet blue status point for an empty record, so the card still moves."""
    return live_dot(cx, cy, BLUE_LIGHT, 3.5)


def _rail(x: float, upper: float, lower: float) -> str:
    """The stretch of rail between two nodes, stopping short of each so a hollow node stays hollow."""
    if lower - upper <= 16:
        return ""
    return f'<path d="M{x:g} {upper + 8:g}V{lower - 8:g}" stroke="{HAIR_STRONG}" stroke-width="2"/>'


def _travel(moves: list[tuple[float, float]], dur: float) -> str:
    """Move the element it sits in (y) from 0 through `moves`, each (second, y) taking ROLL and landing at that second.

    It holds after the last move until dur, so the loop's last frame is the
    last move's: the caller either moves home there or draws its opening rows
    again at that offset.
    """
    points = [(0.0, 0.0)]
    for second, offset in moves:
        points += [(second - ROLL, points[-1][1]), (second, offset)]
    if points[-1][0] < dur:
        points.append((dur, points[-1][1]))
    values, times = keys([(second, f"0 {at:g}") for second, at in points], dur)
    splines = ";".join(
        SMOOTH if a[1] != b[1] else "0 0 1 1" for a, b in pairwise(points)
    )
    return (
        f'<animateTransform attributeName="transform" type="translate" values="{values}" '
        f'keyTimes="{times}" calcMode="spline" keySplines="{splines}" dur="{dur:g}s" repeatCount="indefinite"/>'
    )


def _fade(points: list[tuple[float, float]], dur: float) -> str:
    """An opacity loop through (second, level) points, held from the last point to dur."""
    if points[-1][0] < dur:
        points = [*points, (dur, points[-1][1])]
    values, times = keys([(second, f"{level:g}") for second, level in points], dur)
    return loop("opacity", values, times, dur)


def _move_end(step: int, beat: float = STEP) -> float:
    """When the move for `step` (1-based) lands: FADE before the beat, so the arriving row's fade ends on it."""
    return step * beat - FADE


def _row_fade(index: int, rows: int) -> str:
    """The opacity loop of drawn ledger row `index` while `rows` rows turn through the window.

    A row is at 0 for the whole of any move that carries it across a window
    edge: the top row fades out just before its move, the bottom row fades in
    just after, so the clip never cuts through a line of text.
    """
    level = 1.0 if index < WINDOW else 0.0
    points = [(0.0, level)]
    arrive, leave = (
        index - WINDOW + 1,
        index + 1,
    )  # the steps that bring it in and take it out
    if 1 <= arrive <= rows:
        points += [(_move_end(arrive), 0.0), (_move_end(arrive) + FADE, 1.0)]
    if leave <= rows:
        start = _move_end(leave) - ROLL
        points += [(start - FADE, 1.0), (start, 0.0)]
    return _fade(sorted(points), rows * STEP)


def _on(start: float, end: float, dur: float, fade: float = 0.3) -> str:
    """An opacity loop at 1 from start+fade to end and 0 otherwise; the span may wrap past dur."""
    length = (end - start) % dur or dur

    def level(second: float) -> float:
        since = (second - start) % dur
        if since <= fade:
            return since / fade
        if since <= length:
            return 1.0
        if since <= length + fade:
            return 1 - (since - length) / fade
        return 0.0

    marks = sorted(
        {0.0, dur, start % dur, (start + fade) % dur, end % dur, (end + fade) % dur}
    )
    values, times = keys(
        [(mark, f"{max(0.0, round(level(mark), 3)):g}") for mark in marks], dur
    )
    return loop("opacity", values, times, dur)


def _spotlight(count: int) -> tuple[float, float]:
    """(loop, slot) for a light that visits `count` items in turn."""
    length = T if count <= 6 else 2 * T
    return length, length / count


def _lit(x: float, y: float, w: float, h: float, index: int, count: int) -> str:
    """The spotlight on item `index`: it rests on the first, so the poster shows one lit."""
    if count < 2:
        return ""
    length, slot = _spotlight(count)
    rest = "" if index == 0 else ' opacity="0"'
    return (
        f'<rect x="{x:g}" y="{y:g}" width="{w:.1f}" height="{h:g}" rx="{min(h / 2, 12):g}" '
        f'fill="{BLUE_TINT}" stroke="{BLUE_EDGE}" stroke-width="1.5"{rest}>'
        + _on(index * slot - 0.3, (index + 1) * slot - 0.3, length)
        + "</rect>"
    )


def _in_review_mark(right: float, baseline: float, size: float) -> str:
    """IN REVIEW in amber with its pulsing dot, ending at `right`: the only amber on the cards."""
    wide = _width("IN REVIEW", size, "m")
    return live_dot(right - wide - 11, baseline - size * 0.36, AMBER, 3.5) + text(
        right, baseline, "IN REVIEW", size, AMBER, "m", "end"
    )


def _also_flow(
    also: list[tuple[str, int]],
    left: float,
    right: float,
    baseline: float,
    lines: int,
    pitch: float,
) -> tuple[str, float]:
    """The ALSO MERGED INTO names from `left` on `baseline`, each with its star, in at most `lines` lines.

    At most ALSO_SHOWN names, so both widths name the same ones; past them, or
    past what fits, a "+N more" closes the last line, and names give way from
    the end until it fits. Returns (svg, the baseline of its last line).
    """
    more = _width(f"+{len(also)} more", 12, "c") + ALSO_GAP if len(also) > 1 else 0
    placed, x, line = [], left, 0
    for repo, stars in also[:ALSO_SHOWN]:
        tail = 8 + _star_width(stars, 11.5) if stars else 0
        name = _fit(repo, right - left - tail, 12, "c")
        if x > left and x + _width(name, 12, "c") + tail > right:
            line, x = line + 1, left
            if line >= lines:
                break
        if line == lines - 1:
            # the last line keeps room for a "+N more" after this name
            name = _fit(repo, right - x - tail - more, 12, "c")
            if name != repo and len(name) < 8:
                break
        width = _width(name, 12, "c") + tail
        placed.append((name, stars, x, line, width))
        x += width + ALSO_GAP
    while len(placed) < len(also) and placed:
        _, _, last_x, _, last_w = placed[-1]
        if last_x + last_w + more <= right:
            break
        placed.pop()
    out = []
    for name, stars, x, line, width in placed:
        y = baseline + line * pitch
        out.append(_mono(x, y, name, 12, BLUE_LIGHT))
        if stars:
            out.append(
                _star(x + width - _star_width(stars, 11.5), y, stars, 11.5, META)
            )
    left_out = len(also) - len(placed)
    last = baseline + (placed[-1][3] if placed else 0) * pitch
    if left_out:
        x = placed[-1][2] + placed[-1][4] + ALSO_GAP if placed else left
        out.append(_mono(x, last, f"+{left_out} more", 12, META))
    return "".join(out), last


# ---------------------------------------------------------------- desktop: summary and ledger
RAIL = 48  # the ledger's rail
ROW_X = 68  # where a ledger row's text starts
STAR_X = 752  # the star column; its count reads on from the star
DATE_END = 734  # the date column ends here
TILE_TOP, TILE_H, TILE_GAP = 44, 60, 16


def _ledger_row(row: dict, top: float, newest: bool, above: float | None) -> str:
    """One merge: the rail up to the node above, the node, the repository and its pull request,
    the date and stars on the right, and the title under them."""
    first, second, node = top + 16, top + 33, top + 12
    label = f"#{row['number']}"
    date = row.get("date") or ""
    end = DATE_END - _width(date, 11.5, "c") - 16 if date else STAR_X - 16
    repo = _fit(row["repo"], end - ROW_X - _width(label, 12, "c") - 10, 12, "c")
    out = [
        _rail(RAIL, above, node) if above is not None else "",
        _node(RAIL, node, newest),
        _mono(ROW_X, first, repo, 12, BLUE_LIGHT),
        _mono(ROW_X + _width(repo, 12, "c") + 10, first, label, 12, META),
    ]
    if date:
        out.append(text(DATE_END, first, date, 11.5, META, "c", "end"))
    if row.get("stars"):
        out.append(_star(STAR_X, first, row["stars"], 11.5, INK))
    title = _fit(row["title"], WIDTH - PAD - 16 - ROW_X, 13)
    out.append(text(ROW_X, second, title, 13, INK, "b"))
    return "".join(out)


def _ledger(oss: dict, top: float, shown: int) -> tuple[str, str, float]:
    """The merged ledger from `top`. Returns (svg, its clip, the height it takes)."""
    rows = oss["merged"][:shown]
    hidden, also = _hidden(oss, shown), _also(oss, shown)
    # rows start INSET down the panel and the clip starts INSET - 2 down, so a
    # row that has stepped out of view hides its descenders too
    window = INSET + 2 + (min(len(rows), WINDOW) or 1) * PITCH
    foot = bool(also) + bool(hidden)  # the lines under the ledger's rule
    height = window + (10 + FOOT * foot if foot else 0)
    x, w = PAD, WIDTH - 2 * PAD
    out = [
        f'<rect x="{x}" y="{top:g}" width="{w}" height="{height:g}" rx="10" fill="{CARD}" stroke="{HAIR_STRONG}"/>'
    ]
    clip = f'<clipPath id="ledger"><rect x="{x + 1}" y="{top + INSET - 2:g}" width="{w - 2}" height="{window - INSET + 2:g}"/></clipPath>'
    if not rows:
        out.append(
            _waiting(RAIL, top + 26)
            + text(ROW_X, top + 30, "NO MERGES YET", MICRO, META, "m")
        )
        return "".join(out), clip, height
    # past five rows the ledger turns: every row is drawn again under the last,
    # so after the final step the window holds the opening frame
    turns = len(rows) > WINDOW
    drawn = [*rows, *rows[:WINDOW]] if turns else rows
    body = []
    for index, row in enumerate(drawn):
        y = top + INSET + index * PITCH
        # no rail joins the oldest row to the newest drawn again under it: the
        # log starts over there, and a hairline says so
        above = y - PITCH + 12 if index % len(rows) else None
        line = _ledger_row(row, y, index % len(rows) == 0, above)
        if turns:
            line = f"<g>{_row_fade(index, len(rows))}{line}</g>"
        # the rows in view enter one after another; the ones below wait out of sight
        body.append(group(0.4 + index * STAGGER, line) if index < WINDOW else line)
    moving = ""
    if turns:
        n = len(rows)
        moving = _travel(
            [(_move_end(k), -k * PITCH) for k in range(1, n + 1)], n * STEP
        )
        # the seam shows while the rows on both sides of it do
        start, end = _move_end(n - WINDOW + 1), _move_end(n) - ROLL
        seam = top + INSET + n * PITCH + 1
        body.append(
            f'<path d="M{x + 1} {seam:g}H{x + w - 1}" stroke="{HAIR_STRONG}">'
            + _fade(
                [(0, 0), (start, 0), (start + FADE, 1), (end - FADE, 1), (end, 0)],
                n * STEP,
            )
            + "</path>"
        )
    out.append(f'<g clip-path="url(#ledger)"><g>{moving}{"".join(body)}</g></g>')
    if foot:
        rule = top + window
        out.append(f'<path d="M{x + 1} {rule:g}H{x + w - 1}" stroke="{HAIR}"/>')
        baseline = rule + 22
        if also:
            label = "ALSO MERGED INTO"
            out.append(text(ROW_X, baseline, label, MICRO, META, "m"))
            names, _ = _also_flow(
                also,
                ROW_X + _width(label, MICRO, "m") + 16,
                x + w - 16,
                baseline,
                1,
                FOOT,
            )
            out.append(names)
            baseline += FOOT
        if hidden:
            out.append(text(ROW_X, baseline, _more(hidden), 12.5, BLUE_LIGHT, "s"))
    return "".join(out), clip, height


def _summary(oss: dict, today: str, shown: int) -> str:
    out = [eyebrow(PAD, 30, _first_merge(oss))]
    if today:
        out.append(eyebrow(WIDTH - PAD, 30, f"UPDATED {today}", META, "end"))
    wide = (WIDTH - 2 * PAD - 3 * TILE_GAP) / 4
    for index, (value, label, glyph) in enumerate(_tiles(oss)):
        x = PAD + index * (wide + TILE_GAP)
        # the merged count is the record's headline, so its tile is the emphasised one
        fill, edge = (BLUE_TINT, BLUE_EDGE) if index == 0 else (CARD, HAIR_STRONG)
        out.append(
            group(
                (index + 1) * STAGGER,
                f'<rect x="{x:g}" y="{TILE_TOP}" width="{wide:g}" height="{TILE_H}" rx="10" fill="{fill}" stroke="{edge}"/>'
                + text(x + 16, TILE_TOP + 31, value, 24, INK, "n")
                + text(x + 16, TILE_TOP + TILE_H - 13, label, MICRO, META, "m")
                + _glyph(
                    glyph,
                    x + wide - 30,
                    TILE_TOP + 14,
                    x + 16 + text_width(value, 24) + 8,
                ),
            )
        )
    top = TILE_TOP + TILE_H + 16
    ledger, clip, height = _ledger(oss, top, shown)
    out.append(group(5 * STAGGER, ledger))
    h = top + height + PAD
    return (
        card_open(WIDTH, h, _summary_label(oss, shown), clip) + "".join(out) + SVG_CLOSE
    )


# ---------------------------------------------------------------- desktop: in review
CHIP_TOP, CHIP_H, CHIP_GAP = 46, 28, 8


def _chip(repo: str, count: int, stars: int, room: float) -> tuple[tuple, float]:
    """One repository chip's (name, count, stars) and its width; a name too long for `room` is cut."""
    tail = 0.0
    if count > 1:
        tail += 8 + _width(str(count), 11, "c") + 12
    if stars:
        tail += 14 + _star_width(stars, 11.5)
    name = _fit(repo, room - 28 - tail, 12, "c")
    return (name, count, stars), 14 + _width(name, 12, "c") + tail + 14


def _draw_chip(
    parts: tuple, x: float, y: float, w: float, index: int, count: int
) -> str:
    name, prs, stars = parts
    mid = y + CHIP_H / 2
    out = [
        f'<rect x="{x:g}" y="{y:g}" width="{w:.1f}" height="{CHIP_H}" rx="{CHIP_H / 2:g}" fill="{CARD}" stroke="{HAIR_STRONG}"/>',
        _lit(x, y, w, CHIP_H, index, count),
        _mono(x + 14, mid + 4.3, name, 12, INK),
    ]
    at = x + 14 + _width(name, 12, "c")
    if prs > 1:
        svg, pill = _counter(at + 8, mid, prs, 11)
        out.append(svg)
        at += 8 + pill
    if stars:
        out.append(_star(at + 14, mid + 4.1, stars, 11.5, META))
    return "".join(out)


def _chip_layout(
    repos: list, left: float, right: float, rows: int, total: int
) -> tuple[list, int]:
    """Place chips in at most `rows` rows. Returns ([(parts, x, row, width)], how many of `total` are left out).

    When some are left out, a "+N more" chip must fit on the last row, so chips
    give way from the end until it does. Every chip leaves room for that chip
    after it, so the first one in a row never has to give way.
    """
    room = right - left - CHIP_GAP - chip_width(f"+{total} more")
    placed, x, row = [], left, 0
    for repo, count, stars in repos:
        parts, width = _chip(repo, count, stars, room)
        if x > left and x + width > right:
            row, x = row + 1, left
            if row >= rows:
                break
        placed.append((parts, x, row, width))
        x += width + CHIP_GAP
    while len(placed) < total and placed:
        more = chip_width(f"+{total - len(placed)} more")
        _, last_x, _, last_w = placed[-1]
        if last_x + last_w + CHIP_GAP + more <= right:
            break
        placed.pop()
    return placed, total - len(placed)


def _review(oss: dict, cap: int) -> str:
    repos = _in_review(oss["open"])
    head = _review_head(oss, len(repos))
    out = [eyebrow(PAD, 30, head)]
    if repos:
        out.append(_in_review_mark(WIDTH - PAD, 30, MICRO))
    else:
        out.append(_waiting(PAD + _width(head, MICRO, "m") + 14, 30 - MICRO * 0.36))
    placed, left_out = _chip_layout(
        repos[:cap], PAD, WIDTH - PAD, REVIEW_ROWS, len(repos)
    )
    chips, y = [], CHIP_TOP - CHIP_GAP
    for index, (parts, x, row, width) in enumerate(placed):
        top = CHIP_TOP + row * (CHIP_H + CHIP_GAP)
        chips.append(_draw_chip(parts, x, top, width, index, len(placed)))
        y = top + CHIP_H
    if left_out:
        _, x, row, width = placed[-1]
        top = CHIP_TOP + row * (CHIP_H + CHIP_GAP)
        chips.append(
            chip(
                x + width + CHIP_GAP,
                top + 3,
                f"+{left_out} more",
                META,
                height=CHIP_H - 6,
            )
        )
    out.append(group(STAGGER, "".join(chips)))
    return card_open(WIDTH, y + PAD, _review_label(oss)) + "".join(out) + SVG_CLOSE


# ---------------------------------------------------------------- phone
def _phone_tiles(oss: dict, y: float) -> tuple[str, float]:
    """The four tiles two by two from y. Returns (svg, the height they take)."""
    pad, size, gap = PHONE_PAD, MICRO_PHONE, 8
    wide = (PHONE - 2 * pad - gap) / 2
    tiles = _tiles(oss)
    labels = [wrap_text(label, wide - 24, size, True, TRACK) for _, label, _ in tiles]
    tall = 54 + 13 * (max(len(lines) for lines in labels) - 1)
    out = []
    for index, (value, _, glyph) in enumerate(tiles):
        x = pad + (index % 2) * (wide + gap)
        top = y + (index // 2) * (tall + gap)
        fill, edge = (BLUE_TINT, BLUE_EDGE) if index == 0 else (CARD, HAIR_STRONG)
        body = (
            f'<rect x="{x:g}" y="{top:g}" width="{wide:g}" height="{tall:g}" rx="10" fill="{fill}" stroke="{edge}"/>'
            + text(x + 12, top + 27, value, 22, INK, "n")
            + _glyph(glyph, x + wide - 28, top + 12, x + 12 + text_width(value, 22) + 6)
            + "".join(
                text(x + 12, top + 44 + line * 13, label, size, META, "m")
                for line, label in enumerate(labels[index])
            )
        )
        out.append(group((index + 1) * STAGGER, body))
    return "".join(out), 2 * tall + gap


def _cursor(rail: float, nodes: list[float]) -> str:
    """A ring that visits one merge after another, then fades out on the oldest and back in on the newest.

    Six rows step every 4 s, the beat the desktop ledger steps on. Fewer rows
    share 12 s (up to three) or 24 s, so the loop stays on the page clock.
    """
    n = len(nodes)
    if n < 2:
        return ""
    dur = 12.0 if n <= 3 else 24.0
    beat = dur / n
    home = _move_end(n, beat)
    moves = [(_move_end(k, beat), nodes[k] - nodes[0]) for k in range(1, n)]
    away = home - ROLL
    return (
        f'<circle cx="{rail}" cy="{nodes[0]:g}" r="10" fill="none" stroke="{BLUE_LIGHT}" stroke-width="1.5">'
        + _travel([*moves, (home, 0.0)], dur)
        + _fade([(0, 1), (away - FADE, 1), (away, 0), (home, 0), (dur, 1)], dur)
        + "</circle>"
    )


def _summary_phone(oss: dict, today: str, shown: int) -> str:
    pad, size = PHONE_PAD, MICRO_PHONE
    out = [text(pad, 26, _first_merge(oss), size, BLUE_LIGHT, "m")]
    tiles, tall = _phone_tiles(oss, 40)
    out.append(tiles)
    top = 40 + tall + 12
    rows = oss["merged"][:shown]
    rail, x0, right = pad + 14, pad + 30, PHONE - pad - 10
    room = right - x0
    body, nodes, y = [], [], top + 8
    for index, row in enumerate(rows):
        node = y + 12
        parts = [
            _rail(rail, nodes[-1], node) if nodes else "",
            _node(rail, node, index == 0),
        ]
        nodes.append(node)
        line_y = y + 16
        for line in _lines(row["repo"], room, 12, 2, "c"):
            parts.append(text(x0, line_y, line, 12, BLUE_LIGHT, "c"))
            line_y += 15
        line_y += 3
        for line in _lines(row["title"], room, 13.5, PHONE_TITLE):
            parts.append(text(x0, line_y, line, 13.5, INK, "b"))
            line_y += 18
        meta = "  ".join(filter(None, [f"#{row['number']}", row.get("date") or ""]))
        parts.append(_mono(x0, line_y, meta, size, META, "m"))
        if row.get("stars"):
            parts.append(
                _star(
                    x0 + _width(meta, size, "m") + 12, line_y, row["stars"], size, META
                )
            )
        body.append(group((5 + index) * STAGGER, "".join(parts)))
        y = line_y + 14
    panel = []
    if not rows:
        panel.append(
            _waiting(rail, top + 26)
            + text(x0, top + 30, "NO MERGES YET", size, META, "m")
        )
        y = top + 50
    end = y + 2
    hidden, also = _hidden(oss, shown), _also(oss, shown)
    if hidden or also:
        panel.append(
            f'<path d="M{pad + 1} {end:g}H{PHONE - pad - 1}" stroke="{HAIR}"/>'
        )
        baseline = end + 23
        if also:
            panel.append(text(x0, baseline, "ALSO MERGED INTO", size, META, "m"))
            names, last = _also_flow(also, x0, right, baseline + 21, ALSO_SHOWN, 18)
            panel.append(names)
            baseline = last + 27
        if hidden:
            panel.append(text(x0, baseline, _more(hidden), 13.5, BLUE_LIGHT, "s"))
            baseline += 27
        end = baseline - 27 + 13
    frame = f'<rect x="{pad}" y="{top:g}" width="{PHONE - 2 * pad}" height="{end - top:g}" rx="10" fill="{CARD}" stroke="{HAIR_STRONG}"/>'
    # the ring sits under the rows, so the node it circles is drawn over it
    out.append(
        group(5 * STAGGER, frame + "".join(panel) + _cursor(rail, nodes))
        + "".join(body)
    )
    h = end + 14
    if today:
        out.append(text(pad, end + 30, f"UPDATED {today}", size, META, "m"))
        h = end + 46
    return card_open(PHONE, h, _summary_label(oss, shown)) + "".join(out) + SVG_CLOSE


def _review_phone(oss: dict, cap: int) -> str:
    pad, size = PHONE_PAD, MICRO_PHONE
    repos = _in_review(oss["open"])
    head = _review_head(oss, len(repos))
    out = [text(pad, 26, head, size, BLUE_LIGHT, "m")]
    if repos:
        out.append(_in_review_mark(PHONE - pad, 26, size))
    else:
        out.append(_waiting(pad + _width(head, size, "m") + 14, 26 - size * 0.36))
    shown = repos[:cap]
    x, w = pad, PHONE - 2 * pad
    y, rows = 40.0, []
    for index, (repo, count, stars) in enumerate(shown):
        tail = (_width(str(count), size, "c") + 20 if count > 1 else 0) + (
            _star_width(stars, size) + 8 if stars else 0
        )
        names = _lines(repo, w - 28 - tail, 12.5, 2, "c")
        tall = 16 + 16 * len(names)
        mid = y + tall / 2
        parts = [
            f'<rect x="{x}" y="{y:g}" width="{w}" height="{tall:g}" rx="12" fill="{CARD}" stroke="{HAIR_STRONG}"/>',
            _lit(x, y, w, tall, index, len(shown)),
        ]
        first = mid - 8 * (len(names) - 1) + 4.5
        parts += [
            text(x + 14, first + line * 16, name, 12.5, INK, "c")
            for line, name in enumerate(names)
        ]
        at = x + w - 14
        if stars:
            at -= _star_width(stars, size)
            parts.append(_star(at, mid + 4.1, stars, size, META))
            at -= 8
        if count > 1:
            pill = _width(str(count), size, "c") + 12
            at -= pill
            parts.append(_counter(at, mid, count, size)[0])
        rows.append("".join(parts))
        y += tall + 8
    if len(repos) > len(shown):
        rows.append(
            text(
                x + 2, y + 12, f"+{len(repos) - len(shown)} more", 13.5, BLUE_LIGHT, "s"
            )
        )
        y += 26
    out.append(group(STAGGER, "".join(rows)))
    return card_open(PHONE, y + 12, _review_label(oss)) + "".join(out) + SVG_CLOSE


def render(oss: dict, today: str = "", max_rows: int = MERGED_SHOWN) -> dict[str, str]:
    """Return {output key: svg} for the flat summary and review cards, desktop and phone.

    `today` is the date the UPDATED label shows (left out when empty).
    `max_rows` caps the ledger's rows (six at most) and the repositories the
    review cards name; the rest are counted into "+N more".
    """
    shown = min(max_rows, MERGED_SHOWN)
    return {
        "summary": _summary(oss, today, shown),
        "summary-mobile": _summary_phone(oss, today, shown),
        "review": _review(oss, max_rows),
        "review-mobile": _review_phone(oss, min(max_rows, PHONE_REVIEW)),
    }
