"""Render animated SVG cards of your pull requests to other people's repositories.

Finds your merged and open pull requests with the GitHub GraphQL search API,
drops repositories you own, private repositories, repositories under
OSS_MIN_STARS, and anything matched by OSS_EXCLUDE_OWNERS or OSS_EXCLUDE_REPOS,
then writes up to three SVG cards, each in an 840px desktop layout and a 320px
phone layout:

- a summary: merged upstream, in review, projects contributed to, combined
  stars, and a chip per project ranked by stars
- the merged pull requests, newest first
- the pull requests in review, grouped by repository

GitHub serves README images through an <img>, so every card is self-contained:
no scripts, no external fonts or images, CSS and SMIL animation only.

Inside Actions it also writes a Markdown table of every pull request to the
run's step summary, and with OSS_COMMIT=true it commits and pushes the cards.

If the API fails, the cards already on disk are kept and the run exits 0, so a
flaky API never blanks a README. With no earlier card to keep it exits 1.
Stdlib only: action.yml installs nothing.

Run standalone:
  GITHUB_TOKEN=... OSS_USERNAME=your-login python oss_contributions_card.py
"""

from __future__ import annotations

import http.client
import json
import math
import os
import re
import subprocess
import sys
import unicodedata
import urllib.request
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from html import escape
from pathlib import Path

# Palette and fonts of the profile README cards these designs come from: warm
# near-black, one blue family, green for merged work, amber for work in review.
BG = "#0b1012"
CARD = "#0f171c"
BLUE_LIGHT = "#60a5fa"
SKY = "#38bdf8"
GREEN = "#22c55e"
AMBER = "#f59e0b"
MONO = "'JetBrains Mono','SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"
SANS = "'Segoe UI',Inter,-apple-system,BlinkMacSystemFont,Helvetica,Arial,sans-serif"
SVG_CLOSE = "</svg>"

API_URL = "https://api.github.com/graphql"
ALLOWED_HOSTS = ("https://api.github.com/",)
MAX_PAGES = 10  # 100 results a page, and the search API stops at 1000
REVIEW_NUMBERS = 4  # PR numbers listed per repository before "+N"
OUTPUTS = (
    ("summary", "OSS_OUTPUT_SUMMARY", "assets/oss.svg"),
    ("merged", "OSS_OUTPUT_MERGED", "assets/oss-merged.svg"),
    ("review", "OSS_OUTPUT_REVIEW", "assets/oss-review.svg"),
    ("summary-mobile", "OSS_OUTPUT_SUMMARY_MOBILE", "assets/oss-mobile.svg"),
    ("merged-mobile", "OSS_OUTPUT_MERGED_MOBILE", "assets/oss-merged-mobile.svg"),
    ("review-mobile", "OSS_OUTPUT_REVIEW_MOBILE", "assets/oss-review-mobile.svg"),
)
COMMIT_MESSAGE = "chore: refresh oss contribution cards"
# The identity actions/checkout documents for commits made by the workflow token.
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

# A login goes into the search query, so nothing else may: no spaces, no colons.
LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
HEX_COLOR = re.compile(r"#(?:[0-9a-f]{3}){1,2}")
# An exclude-repos entry: owner/repo, or owner/* for every repository of an owner.
REPO = re.compile(r"[A-Za-z0-9_.-]+/(?:\*|[A-Za-z0-9_.-]+)")

# Code points dropped from API text: emoji and pictographs with their
# presentation selector, keycap and tag characters, then everything XML 1.0
# does not allow. Written as numbers so this file stays plain ASCII.
DROPPED_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x2B05, 0x2B07),
    (0x2B1B, 0x2B1C),
    (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
    (0x231A, 0x231B),
    (0x23E9, 0x23F3),
    (0x23F8, 0x23FA),
    (0x20E3, 0x20E3),
    (0xFE0F, 0xFE0F),
    (0xE0020, 0xE007F),
    (0x00, 0x08),
    (0x0B, 0x0C),
    (0x0E, 0x1F),
    (0xD800, 0xDFFF),
    (0xFFFE, 0xFFFF),
)
CLEAN = {cp: None for lo, hi in DROPPED_RANGES for cp in range(lo, hi + 1)}
# figure dash, en dash, em dash and horizontal bar all become a plain hyphen
CLEAN.update(dict.fromkeys(range(0x2012, 0x2016), "-"))

SEARCH_QUERY = (
    "query($q: String!, $after: String) {"
    " search(query: $q, type: ISSUE, first: 100, after: $after) {"
    " issueCount pageInfo { hasNextPage endCursor }"
    " nodes { ... on PullRequest { title number url mergedAt"
    " repository { nameWithOwner stargazerCount isPrivate owner { login } } } } } }"
)

EMPTY_MERGED = (
    "No merged pull requests yet",
    "Pull requests merged into repositories you do not own are listed here, newest first.",
    "",
)
EMPTY_REVIEW = (
    "No pull requests in review",
    "Open pull requests to repositories you do not own are listed here, grouped by repository.",
    "",
)


class ConfigError(Exception):
    """An input the action cannot run with."""


class ApiError(Exception):
    """The GraphQL API answered, but not with search results."""


# Every way a request or its response can fail. OSError covers URLError,
# HTTPError and timeouts; ValueError covers a body that is not JSON.
FETCH_ERRORS = (ApiError, OSError, ValueError, http.client.HTTPException)


@dataclass(frozen=True)
class PullRequest:
    repo: str
    owner: str
    title: str
    number: int
    url: str
    merged_at: str
    stars: int
    private: bool


@dataclass(frozen=True)
class Config:
    username: str
    token: str
    exclude_owners: frozenset[str]
    exclude_repos: frozenset[str]
    outputs: dict[str, Path]
    max_rows: int
    accent: str
    min_stars: int = 0
    commit: bool = False
    commit_message: str = COMMIT_MESSAGE


def _whole_number(
    env: Mapping[str, str], name: str, default: str, pattern: str, label: str, low: int
) -> int:
    """Read an ASCII whole-number input, or raise ConfigError naming its floor."""
    value = (env.get(name) or default).strip()
    if not re.fullmatch(pattern, value, re.ASCII):
        raise ConfigError(
            f"{label} must be a whole number of {low} or more, got {value!r}"
        )
    return int(value)


def load_config(env: Mapping[str, str]) -> Config:
    """Read the action inputs from the environment, or raise ConfigError."""
    username = env.get("OSS_USERNAME", "").strip()
    if not LOGIN.fullmatch(username):
        raise ConfigError(
            f"username must be a GitHub login, got {username!r} "
            "(the username input, or OSS_USERNAME when running by hand)"
        )
    token = (env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or "").strip()
    if not token:
        raise ConfigError(
            "no token: set the token input, or GITHUB_TOKEN when running by hand"
        )
    outputs = {
        card: Path(path)
        for card, name, default in OUTPUTS
        if (path := env.get(name, default).strip())
    }
    if not outputs:
        raise ConfigError("every output path is empty, so there is nothing to render")
    rows = _whole_number(env, "OSS_MAX_ROWS", "12", r"[1-9]\d*", "max-rows", 1)
    accent = env.get("OSS_ACCENT", "").strip().lower()
    if accent and not HEX_COLOR.fullmatch(accent):
        raise ConfigError(f"accent must be a hex color like #a78bfa, got {accent!r}")
    if len(accent) == 4:  # #abc to #aabbcc, so an alpha suffix can be appended
        accent = "#" + "".join(c * 2 for c in accent[1:])
    owners = env.get("OSS_EXCLUDE_OWNERS", "").split(",")
    repos = [
        r.strip() for r in env.get("OSS_EXCLUDE_REPOS", "").split(",") if r.strip()
    ]
    bad = [r for r in repos if not REPO.fullmatch(r)]
    if bad:
        raise ConfigError(
            f"exclude-repos entries must be owner/repo or owner/*, got {', '.join(map(repr, bad))}"
        )
    min_stars = _whole_number(env, "OSS_MIN_STARS", "0", r"\d+", "min-stars", 0)
    commit = (env.get("OSS_COMMIT") or "false").strip().lower()
    if commit not in ("true", "false"):
        raise ConfigError(f"commit must be true or false, got {commit!r}")
    message = (env.get("OSS_COMMIT_MESSAGE") or "").strip() or COMMIT_MESSAGE
    return Config(
        username=username,
        token=token,
        exclude_owners=frozenset(o.strip() for o in owners if o.strip()),
        exclude_repos=frozenset(repos),
        outputs=outputs,
        max_rows=rows,
        accent=accent,
        min_stars=min_stars,
        commit=commit == "true",
        commit_message=message,
    )


# ---------------------------------------------------------------- GitHub API


def fetch(url: str, body: dict, token: str, timeout: int = 30) -> bytes:
    """POST a JSON body and return the raw response. https to allowlisted hosts only."""
    if not url.startswith(ALLOWED_HOSTS):
        raise ValueError(f"refusing to fetch {url}")
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "oss-contributions-card-action",
        },
    )
    # scheme and host were checked against ALLOWED_HOSTS above
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        return resp.read()


def graphql(query: str, variables: dict, token: str) -> dict:
    """Run one GraphQL request and return its data. Any reported error raises ApiError."""
    payload = json.loads(
        fetch(API_URL, {"query": query, "variables": variables}, token)
    )
    if not isinstance(payload, dict):
        raise ApiError("the GraphQL API sent an unexpected response")
    if payload.get("errors"):
        errors = json.dumps(payload["errors"])[:300]
        raise ApiError(f"the GraphQL API reported errors: {errors}")
    if not isinstance(payload.get("data"), dict):
        raise ApiError("the GraphQL API sent no data")
    return payload["data"]


def plain(text: str) -> str:
    """Return API text with dashes flattened and emoji and XML-invalid characters dropped."""
    return " ".join(text.translate(CLEAN).split())


def parse_node(node: dict | None) -> PullRequest | None:
    """Return the pull request in one search node, or None for an empty node."""
    if not node or not node.get("repository"):
        return None  # a result the PullRequest fragment did not match
    repo = node["repository"]
    return PullRequest(
        repo=repo["nameWithOwner"],
        owner=repo["owner"]["login"],
        title=plain(node["title"]),
        number=int(node["number"]),
        url=node["url"],
        merged_at=node.get("mergedAt") or "",
        stars=int(repo.get("stargazerCount") or 0),
        private=bool(repo.get("isPrivate")),
    )


def search_prs(username: str, state: str, token: str) -> list[PullRequest]:
    """Return every pull request by username, in one state, to repositories they do not own."""
    query = f"is:pr author:{username} is:{state} -user:{username}"
    found: dict[str, PullRequest] = {}
    after = None
    total = 0
    for _ in range(MAX_PAGES):
        data = graphql(SEARCH_QUERY, {"q": query, "after": after}, token)
        try:
            search = data["search"]
            total = search["issueCount"]
            for node in search["nodes"]:
                pr = parse_node(node)
                if pr:
                    found.setdefault(pr.url, pr)  # a page boundary can repeat a result
            after = search["pageInfo"]["endCursor"]
            more = search["pageInfo"]["hasNextPage"]
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ApiError(f"unexpected search response ({exc!r})") from exc
        if not (more and after):
            break
    if total > MAX_PAGES * 100:
        print(
            f"::warning::GitHub search found {total} {state} pull requests but "
            f"returns at most {MAX_PAGES * 100}; the cards count {len(found)}."
        )
    return list(found.values())


def select_upstream(
    prs: Iterable[PullRequest],
    username: str,
    exclude_owners: Iterable[str],
    exclude_repos: Iterable[str] = (),
    min_stars: int = 0,
) -> list[PullRequest]:
    """Return the pull requests to public repositories someone else owns, minus exclusions.

    Every comparison is case-insensitive. An exclude_repos entry is owner/repo,
    or owner/* to drop every repository of that owner. Repositories with fewer
    than min_stars stars are dropped too.
    """
    owners = {o.lower() for o in exclude_owners} | {username.lower()}
    repos: set[str] = set()
    for entry in exclude_repos:
        owner, _, name = entry.lower().partition("/")
        if name == "*":
            owners.add(owner)
        else:
            repos.add(f"{owner}/{name}")
    return [
        pr
        for pr in prs
        if not pr.private
        and pr.owner.lower() not in owners
        and pr.repo.lower() not in repos
        and pr.stars >= min_stars
    ]


def projects(merged: Iterable[PullRequest]) -> dict[str, tuple[int, int]]:
    """Return {repository: (merged pull requests, stars)}, biggest projects first."""
    counts: Counter[str] = Counter()
    stars: dict[str, int] = {}
    for pr in merged:
        counts[pr.repo] += 1
        stars[pr.repo] = pr.stars
    ranked = sorted(counts, key=lambda r: (-stars[r], -counts[r], r.lower()))
    return {r: (counts[r], stars[r]) for r in ranked}


def summarize(merged: list[PullRequest], open_prs: list[PullRequest]) -> dict[str, int]:
    """Return the numbers the action reports as outputs."""
    ranked = projects(merged)
    return {
        "merged": len(merged),
        "open": len(open_prs),
        "projects": len(ranked),
        "stars": sum(stars for _, stars in ranked.values()),
    }


# ---------------------------------------------------------------- cards


def svg_open(w: int, h: int, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-label="{escape(label)}">'
    )


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3].rsplit(" ", 1)[0] + "..."


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _compact(n: int) -> str:
    """Return a star total the way its tile shows it: 850, 12K+, 1.2M+."""
    if n >= 1_000_000:
        return f"{n // 100_000 / 10:g}M+"
    if n >= 1000:
        return f"{n // 1000}K+"
    return str(n)


def _oss_chip_label(repo: str, count: int, stars: int) -> str:
    """Return a chip label: repo, a count when merged more than once, and its stars."""
    label = _clip(repo, 60)
    if count > 1:
        label += f"  x{count}"
    if stars >= 1_000_000:
        label += f"  {stars / 1_000_000:.1f}M"
    elif stars >= 1000:
        label += f"  {stars / 1000:.1f}K"
    elif stars:
        label += f"  {stars}"
    return label


def render_summary(
    merged: list[PullRequest], open_prs: list[PullRequest], accent: str = ""
) -> str:
    """Return the summary card: four count tiles, then a chip per project by stars."""
    ranked = projects(merged)
    reach = sum(stars for _, stars in ranked.values())
    kicker = accent or BLUE_LIGHT
    chip = accent or SKY
    w, h = 840, 250
    tiles = [
        (str(len(merged)), "merged upstream"),
        (str(len(open_prs)), "in review"),
        (str(len(ranked)), "projects contributed to"),
        (_compact(reach), "combined stars"),
    ]
    parts = [
        svg_open(
            w,
            h,
            f"Open source: {len(merged)} merged upstream, {len(open_prs)} in review, across {len(ranked)} projects",
        ),
        f"<style>.m{{font-family:{MONO};font-weight:700;letter-spacing:1.2px}}.v{{font-family:{SANS};font-weight:800}}</style>",
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="14" fill="{BG}" stroke="rgba(255,255,255,0.08)"/>',
        f'<text class="m" x="24" y="30" fill="{kicker}" font-size="10">OPEN SOURCE  |  MERGED UPSTREAM</text>',
    ]
    tw = (w - 32 - 3 * 10) / 4
    for i, (value, label) in enumerate(tiles):
        x = 16 + i * (tw + 10)
        parts.append(
            f'<g opacity="0"><animate attributeName="opacity" to="1" begin="{0.1 + i * 0.1:.1f}s" dur="0.4s" fill="freeze"/>'
            f'<rect x="{x:.1f}" y="44" width="{tw:.1f}" height="62" rx="10" fill="{CARD}" stroke="rgba(255,255,255,0.07)"/>'
            f'<text class="v" x="{x + 14:.1f}" y="76" fill="#f3f4f6" font-size="22">{value}</text>'
            f'<text class="m" x="{x + 14:.1f}" y="95" fill="rgba(255,255,255,0.5)" font-size="8">{label.upper()}</text></g>'
        )
    if not ranked:
        parts.append(
            '<g opacity="0"><animate attributeName="opacity" to="1" begin="0.5s" dur="0.4s" fill="freeze"/>'
            '<text class="m" x="24" y="143" fill="rgba(255,255,255,0.5)" font-size="9">'
            "NO MERGED PULL REQUESTS YET  |  PROJECTS SHOW UP HERE AS YOUR WORK LANDS</text></g>"
        )
    # merged-into chips, biggest projects first
    labels = [_oss_chip_label(r, count, stars) for r, (count, stars) in ranked.items()]
    for i, (x, y, cw, label) in enumerate(_layout_chips(labels, w, h)):
        parts.append(
            f'<g opacity="0"><animate attributeName="opacity" to="1" begin="{0.5 + i * 0.06:.2f}s" dur="0.4s" fill="freeze"/>'
            f'<rect x="{x:.1f}" y="{y}" width="{cw:.1f}" height="22" rx="11" fill="{chip}12" stroke="{chip}44"/>'
            f'<text class="m" x="{x + cw / 2:.1f}" y="{y + 15}" text-anchor="middle" fill="rgba(255,255,255,0.8)" font-size="9">{escape(label)}</text></g>'
        )
    parts.append(SVG_CLOSE)
    return "".join(parts)


def _layout_chips(
    labels: list[str], w: int, h: int
) -> list[tuple[float, int, float, str]]:
    """Return (x, y, width, label) per chip, wrapping rows; overflow ends on a "+N more" chip."""
    placed: list[tuple[float, int, float, str]] = []
    x, y = 24.0, 128
    for label in labels:
        cw = 16 + len(label) * 6.3
        if x + cw > w - 24:
            x, y = 24.0, y + 30
        if y > h - 30:
            break
        placed.append((x, y, cw, label))
        x += cw + 8
    hidden = len(labels) - len(placed)
    # A chip is under 500px wide (repo clipped to 60 characters), so "+N more"
    # always fits after the first chip of a row: this only pops within the
    # last row.
    while hidden:
        more = f"+{hidden} more"
        mw = 16 + len(more) * 6.3
        lx, ly, lw, _ = placed[-1]
        if lx + lw + 8 + mw <= w - 24:
            placed.append((lx + lw + 8, ly, mw, more))
            break
        placed.pop()
        hidden += 1
    return placed


def render_list_card(
    kicker: str, rows: list[tuple[str, str, str]], accent: str, footer: str = ""
) -> str:
    """Return a card of rows: bold primary, dimmed secondary line, mono meta on the right."""
    w = 840
    row_h = 46
    top = 50
    h = top + len(rows) * row_h + (34 if footer else 12)
    parts = [
        svg_open(
            w, h, kicker.title() + ": " + "; ".join(f"{a} {b} {c}" for a, b, c in rows)
        ),
        (
            f"<style>.m{{font-family:{MONO};font-weight:700;letter-spacing:1.2px}}.t{{font-family:{SANS};font-weight:700}}"
            f".s{{font-family:{SANS};font-weight:500}}</style>"
        ),
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="14" fill="{BG}" stroke="rgba(255,255,255,0.08)"/>',
        f'<text class="m" x="24" y="31" fill="{accent}" font-size="10">{escape(kicker)}</text>',
    ]
    for i, (primary, secondary, meta) in enumerate(rows):
        y = top + i * row_h
        begin = 0.15 + i * 0.07
        parts.append(
            f'<g opacity="0"><animate attributeName="opacity" to="1" begin="{begin:.2f}s" dur="0.4s" fill="freeze"/>'
            f'<animateTransform attributeName="transform" type="translate" from="-8 0" to="0 0" begin="{begin:.2f}s" dur="0.4s" fill="freeze"/>'
            f'<line x1="24" y1="{y}" x2="{w - 24}" y2="{y}" stroke="rgba(255,255,255,0.06)"/>'
            f'<circle cx="30" cy="{y + 23}" r="3" fill="{accent}"/>'
            f'<text class="t" x="44" y="{y + 20}" fill="#f3f4f6" font-size="13.5">{escape(_clip(primary, 60))}</text>'
            f'<text class="s" x="44" y="{y + 37}" fill="rgba(255,255,255,0.6)" font-size="11.5">{escape(_clip(secondary, 104))}</text>'
            f'<text class="m" x="{w - 24}" y="{y + 20}" text-anchor="end" fill="rgba(255,255,255,0.45)" font-size="9">{escape(meta.upper())}</text></g>'
        )
    if footer:
        parts.append(
            f'<text class="s" x="24" y="{h - 14}" fill="rgba(255,255,255,0.55)" font-size="11">{escape(_clip(footer, 150))}</text>'
        )
    parts.append(SVG_CLOSE)
    return "".join(parts)


def render_merged(merged: list[PullRequest], max_rows: int) -> str:
    """Return the merged card: one row per pull request, newest first."""
    newest = sorted(merged, key=lambda pr: (pr.merged_at, pr.url), reverse=True)
    rows = [(pr.repo, pr.title, f"#{pr.number}") for pr in newest[:max_rows]]
    if not rows:
        return render_list_card("0 MERGED UPSTREAM", [EMPTY_MERGED], GREEN)
    hidden = len(newest) - len(rows)
    footer = f"+{_plural(hidden, 'more merged pull request')}" if hidden else ""
    return render_list_card(
        f"{len(newest)} MERGED UPSTREAM  |  NEWEST FIRST", rows, GREEN, footer
    )


def _numbers(prs: list[PullRequest]) -> str:
    labels = [f"#{pr.number}" for pr in prs[:REVIEW_NUMBERS]]
    if len(prs) > REVIEW_NUMBERS:
        labels.append(f"+{len(prs) - REVIEW_NUMBERS}")
    return ", ".join(labels)


def _by_repository(open_prs: list[PullRequest]) -> list[list[PullRequest]]:
    """Group open pull requests by repository, most open pull requests first."""
    grouped: dict[str, list[PullRequest]] = {}
    for pr in sorted(open_prs, key=lambda pr: pr.number):
        grouped.setdefault(pr.repo, []).append(pr)
    return sorted(
        grouped.values(),
        key=lambda prs: (-len(prs), -prs[0].stars, prs[0].repo.lower()),
    )


def render_review(open_prs: list[PullRequest], max_rows: int) -> str:
    """Return the in-review card: one row per repository, most open pull requests first."""
    ordered = _by_repository(open_prs)
    rows = [
        (prs[0].repo, "; ".join(pr.title for pr in prs), _numbers(prs))
        for prs in ordered[:max_rows]
    ]
    count = len(open_prs)
    kicker = f"{count} PR{'' if count == 1 else 'S'} IN REVIEW"
    if not rows:
        return render_list_card(kicker, [EMPTY_REVIEW], AMBER)
    hidden = sum(len(prs) for prs in ordered[max_rows:])
    footer = f"+{_plural(hidden, 'more pull request')} in review" if hidden else ""
    return render_list_card(kicker, rows, AMBER, footer)


# ---------------------------------------------------------------- phone cards

# The phone layouts come from the profile README's mobile_cards.py: a 320px
# column that a <picture> source picks below 600px, so text renders near its
# real size on a phone instead of an 840px card scaled down. Text wraps instead
# of clipping, blocks fade and rise in order, the accent bar pulses and a shine
# sweeps the card.
PHONE_W, PHONE_PAD, PHONE_BODY = 320, 18, 15
PHONE_CONTENT = PHONE_W - 2 * PHONE_PAD
WHITE, MUTED, BORDER = "#f3f4f6", "#b1bfcc", "#26343d"
LEADING = 0.38  # gap below each line, as a share of its font size
STAGGER, FADE, LAST_START = 0.1, 0.45, 2.4
PHONE_MERGED_ROWS, PHONE_REVIEW_ROWS, PHONE_CHIPS = 6, 5, 12


def _advance(character: str) -> float:
    """Return a conservative sans-serif glyph width, as a share of the font size."""
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


def text_width(text: str, size: float = PHONE_BODY, mono: bool = False) -> float:
    """Measure text conservatively: sans glyph advances, or monospace plus tracking."""
    if mono:
        return len(text) * (size * 0.6 + 1)
    return sum(_advance(character) for character in text) * size


def wrap_text(
    text: str, width: float, size: float = PHONE_BODY, mono: bool = False
) -> list[str]:
    """Wrap words to a width, splitting a token too long for one line without dropping any of it."""
    lines, current = [], ""
    for word in str(text).split():
        candidate = f"{current} {word}" if current else word
        if text_width(candidate, size, mono) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        *full, current = _break_word(word, width, size, mono)
        lines.extend(full)
    if current:
        lines.append(current)
    return lines


def _break_word(word: str, width: float, size: float, mono: bool) -> list[str]:
    """Split a word too long for one line; the last piece stays open for the next word."""
    lines, current = [], ""
    # break after "/", "-", "_" or "." first, and between letters only
    # where no separator fits
    for piece in re.findall(r"[^/\-_.]+[/\-_.]*|[/\-_.]+", word):
        if current and text_width(current + piece, size, mono) > width:
            lines.append(current)
            current = ""
        for character in piece:
            if current and text_width(current + character, size, mono) > width:
                lines.append(current)
                current = ""
            current += character
    return [*lines, current]


def _phone_text(
    x: float, y: float, size: float, weight: int, color: str, text: str, mono: bool
) -> str:
    font = f' font-family="{MONO}" letter-spacing="1"' if mono else ""
    return (
        f'<text x="{x:g}" y="{y:g}" font-size="{size:g}" font-weight="{weight}" '
        f'fill="{color}"{font}>{escape(text)}</text>'
    )


def _enter(begin: float, body: str) -> str:
    """Fade in while rising 10px, once, then hold."""
    return (
        f'<g opacity="0"><animate attributeName="opacity" to="1" begin="{begin:.2f}s" dur="{FADE}s" fill="freeze"/>'
        f'<animateTransform attributeName="transform" type="translate" from="0 10" to="0 0" '
        f'begin="{begin:.2f}s" dur="{FADE}s" fill="freeze"/>{body}</g>'
    )


class PhoneCard:
    """One phone card: a column of staggered blocks inside the shared frame."""

    def __init__(self, name: str, accent: str) -> None:
        self.name, self.accent = name, accent
        self.parts: list[str] = []
        self.y: float = PHONE_PAD
        self.begin = 0.15
        self._depth = 0

    @contextmanager
    def block(self, step: float = STAGGER) -> Iterator[None]:
        """Draw everything inside as one entrance, after the previous block."""
        start = len(self.parts)
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
            if self._depth == 0 and len(self.parts) > start:
                body = "".join(self.parts[start:])
                del self.parts[start:]
                self.parts.append(_enter(self.begin, body))
                self.begin = min(self.begin + step, LAST_START)

    def lines(
        self,
        text: str,
        *,
        x: float = PHONE_PAD,
        y: float | None = None,
        width: float = PHONE_CONTENT,
        size: float = PHONE_BODY,
        color: str = WHITE,
        weight: int = 500,
        mono: bool = False,
    ) -> float:
        """Write wrapped text from y (default: the cursor) and return the y below it."""
        cursor = self.y if y is None else y
        with self.block():
            for line in wrap_text(text, width, size, mono):
                cursor += size
                self.parts.append(
                    _phone_text(x, cursor, size, weight, color, line, mono)
                )
                cursor += size * LEADING
        if y is None:
            self.y = cursor
        return cursor

    def label(self, text: str) -> None:
        """Write a mono micro-label in the accent color."""
        self.lines(text.upper(), size=11, color=self.accent, weight=700, mono=True)
        self.y += 8

    def divider(self) -> None:
        """Draw a hairline across the card that strokes in from the left."""
        self.y += 6
        with self.block():
            self.parts.append(
                f'<path d="M{PHONE_PAD} {self.y:g}H{PHONE_W - PHONE_PAD}" stroke="{BORDER}" '
                'stroke-width="1" fill="none" pathLength="1" stroke-dasharray="1">'
                f'<animate attributeName="stroke-dashoffset" values="1;0" begin="{self.begin:.2f}s" '
                'dur="0.6s" fill="freeze"/></path>'
            )
        self.y += 14

    def row(self, title: str, detail: str = "", meta: str = "") -> None:
        """Write a bulleted row: bold title, mono meta in the accent color, muted detail."""
        x = PHONE_PAD + 14
        width = PHONE_W - PHONE_PAD - x
        with self.block():
            self.parts.append(
                f'<circle cx="{PHONE_PAD + 3}" cy="{self.y + 14 * 0.65:g}" r="2.5" fill="{self.accent}"/>'
            )
            self.lines(title, x=x, width=width, size=14, weight=650)
            if meta:
                self.y += 3
                self.lines(
                    meta.upper(),
                    x=x,
                    width=width,
                    size=10.5,
                    color=self.accent,
                    weight=700,
                    mono=True,
                )
            if detail:
                self.y += 3
                self.lines(detail, x=x, width=width, size=13.5, color=MUTED)
        self.y += 12

    def metrics(self, items: list[tuple[str, str]]) -> None:
        """Lay out value-and-label tiles two to a row."""
        gap, inset = 10, 10
        tile = (PHONE_CONTENT - gap) / 2
        inner = tile - 2 * inset
        for index in range(0, len(items), 2):
            group = items[index : index + 2]
            height = max(
                22
                + len(wrap_text(value, inner, 22)) * 22 * (1 + LEADING)
                + len(wrap_text(label, inner, 12)) * 12 * (1 + LEADING)
                for value, label in group
            )
            for column, (value, label) in enumerate(group):
                x = PHONE_PAD + column * (tile + gap)
                with self.block():
                    self.parts.append(
                        f'<rect x="{x:g}" y="{self.y:g}" width="{tile:g}" '
                        f'height="{height:g}" rx="10" fill="{CARD}" stroke="{BORDER}"/>'
                    )
                    bottom = self.lines(
                        value,
                        x=x + inset,
                        y=self.y + 8,
                        width=inner,
                        size=22,
                        color=self.accent,
                        weight=750,
                    )
                    self.lines(
                        label,
                        x=x + inset,
                        y=bottom + 2,
                        width=inner,
                        size=12,
                        color=MUTED,
                    )
            self.y += height + gap

    def chips(self, labels: list[str], tint: str, size: float = 10.5) -> None:
        """Lay out mono chips in rows; a label wider than the card wraps inside its chip."""
        x, line_bottom = float(PHONE_PAD), self.y
        for label in labels:
            chip_width = min(PHONE_CONTENT, text_width(label, size, True) + 18)
            # 2px of slack so a label measured to fit never wraps inside its own chip
            rows = len(wrap_text(label, chip_width - 16, size, True))
            chip_height = rows * size * (1 + LEADING) + 10
            if x + chip_width > PHONE_W - PHONE_PAD:
                x, self.y = float(PHONE_PAD), line_bottom + 6
            with self.block(step=0.04):
                self.parts.append(
                    f'<rect x="{x:g}" y="{self.y:g}" width="{chip_width:g}" '
                    f'height="{chip_height:g}" rx="8" fill="{tint}12" stroke="{tint}44"/>'
                )
                self.lines(
                    label,
                    x=x + 9,
                    y=self.y + 4,
                    width=chip_width - 16,
                    size=size,
                    color="rgba(255,255,255,0.85)",
                    mono=True,
                )
            line_bottom = max(line_bottom, self.y + chip_height)
            x += chip_width + 6
        self.y = line_bottom + 12

    def finish(self) -> str:
        """Close the card: frame, pulsing accent bar, the blocks, then a repeating shine."""
        height = int(self.y + PHONE_PAD + 0.999)
        # skewX(-18) leans the shine left as it goes down, so tall cards travel further
        sweep = PHONE_W + 280 + math.ceil(height * 0.33)
        return (
            svg_open(PHONE_W, height, self.name)
            + f"<title>{escape(self.name)}</title>"
            + f"<style>text{{font-family:{SANS};font-variant-numeric:tabular-nums}}</style>"
            + '<defs><linearGradient id="shine" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
            '<stop offset="0.5" stop-color="#fff" stop-opacity="0.06"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            f'<clipPath id="card"><rect x="1" y="1" width="{PHONE_W - 2}" height="{height - 2}" rx="14"/></clipPath></defs>'
            f'<rect x=".5" y=".5" width="{PHONE_W - 1}" height="{height - 1}" rx="14" fill="{BG}" stroke="{BORDER}"/>'
            f'<rect x="0" y="20" width="3" height="26" rx="1.5" fill="{self.accent}">'
            '<animate attributeName="opacity" values="1;0.4;1" dur="3s" repeatCount="indefinite"/></rect>'
            + "".join(self.parts)
            + f'<g clip-path="url(#card)"><rect x="-140" y="0" width="120" height="{height}" '
            'fill="url(#shine)" transform="skewX(-18)">'
            f'<animateTransform attributeName="transform" type="translate" values="0 0;{sweep} 0" '
            f'dur="7s" begin="{self.begin + 0.5:.2f}s" repeatCount="indefinite" additive="sum"/></rect></g>'
            + SVG_CLOSE
        )


def render_summary_mobile(
    merged: list[PullRequest], open_prs: list[PullRequest], accent: str = ""
) -> str:
    """Return the phone summary: four tiles two by two, then a chip per project by stars."""
    ranked = projects(merged)
    reach = sum(stars for _, stars in ranked.values())
    card = PhoneCard(
        f"Open source: {len(merged)} merged upstream, {len(open_prs)} in review, across {len(ranked)} projects",
        accent or BLUE_LIGHT,
    )
    card.label("Open source | merged upstream")
    card.metrics(
        [
            (str(len(merged)), "Merged upstream"),
            (str(len(open_prs)), "In review"),
            (str(len(ranked)), "Projects contributed to"),
            (_compact(reach), "Combined stars"),
        ]
    )
    if not ranked:
        card.lines(
            "No merged pull requests yet. Projects show up here as your work lands.",
            size=13.5,
            color=MUTED,
        )
        return card.finish()
    labels = [_oss_chip_label(r, count, stars) for r, (count, stars) in ranked.items()]
    shown = labels[:PHONE_CHIPS]
    if len(labels) > len(shown):
        shown.append(f"+{len(labels) - len(shown)} more")
    card.label("Merged into")
    card.chips(shown, accent or SKY)
    return card.finish()


def _phone_list(
    kicker: str,
    rows: list[tuple[str, str, str]],
    accent: str,
    footer: str,
) -> str:
    """Return a phone list card: one bulleted row per entry, then an optional footer."""
    card = PhoneCard(
        kicker + ": " + "; ".join(f"{a} {c} {b}" for a, b, c in rows),
        accent,
    )
    card.label(kicker)
    for index, (title, detail, meta) in enumerate(rows):
        if index:
            card.divider()
        card.row(title, _clip(detail, 140), meta)
    if footer:
        card.lines(footer, size=14, color=accent, weight=650)
        card.y += 4
    return card.finish()


def render_merged_mobile(merged: list[PullRequest], max_rows: int) -> str:
    """Return the phone merged card: the newest pull requests with their merge dates."""
    newest = sorted(merged, key=lambda pr: (pr.merged_at, pr.url), reverse=True)
    if not newest:
        return _phone_list("0 merged upstream", [EMPTY_MERGED], GREEN, "")
    shown = newest[: min(max_rows, PHONE_MERGED_ROWS)]
    rows = [
        (
            pr.repo,
            pr.title,
            f"PR #{pr.number}" + (f" | {pr.merged_at[:10]}" if pr.merged_at else ""),
        )
        for pr in shown
    ]
    hidden = len(newest) - len(shown)
    footer = f"+{_plural(hidden, 'more merged pull request')}" if hidden else ""
    return _phone_list(
        f"{len(newest)} merged upstream | newest first", rows, GREEN, footer
    )


def render_review_mobile(open_prs: list[PullRequest], max_rows: int) -> str:
    """Return the phone in-review card: one row per repository, most open pull requests first."""
    ordered = _by_repository(open_prs)
    count = len(open_prs)
    kicker = f"{count} PR{'' if count == 1 else 's'} in review"
    if not ordered:
        return _phone_list(kicker, [EMPTY_REVIEW], AMBER, "")
    shown = ordered[: min(max_rows, PHONE_REVIEW_ROWS)]
    rows = [
        (prs[0].repo, "; ".join(pr.title for pr in prs), _numbers(prs)) for prs in shown
    ]
    hidden = sum(len(prs) for prs in ordered[len(shown) :])
    footer = f"+{_plural(hidden, 'more pull request')} in review" if hidden else ""
    return _phone_list(kicker, rows, AMBER, footer)


# ---------------------------------------------------------------- step summary


def _md(text: str) -> str:
    """Escape untrusted text for one Markdown table cell."""
    return re.sub(r"([\\`*_\[\]<>|])", r"\\\1", text)


def step_summary(
    username: str,
    merged: list[PullRequest],
    open_prs: list[PullRequest],
    left_out: int,
) -> str:
    """Return the Markdown the run page shows: the counts, then every pull request."""
    stats = summarize(merged, open_prs)
    lines = [
        f"### Open source contributions by @{username}",
        "",
        "| Merged upstream | In review | Projects | Combined stars |",
        "| ---: | ---: | ---: | ---: |",
        f"| {stats['merged']} | {stats['open']} | {stats['projects']} | {stats['stars']:,} |",
        "",
        (
            f"{_plural(left_out, 'pull request')} left out: your own repositories, "
            "private repositories, `exclude-owners`, `exclude-repos` and `min-stars`."
        ),
    ]
    newest = sorted(merged, key=lambda pr: (pr.merged_at, pr.url), reverse=True)
    if newest:
        lines += [
            "",
            f"#### Merged ({len(newest)})",
            "",
            "| Merged | Repository | Stars | Pull request |",
            "| --- | --- | ---: | --- |",
        ]
        lines += [
            f"| {pr.merged_at[:10]} | {_md(pr.repo)} | {pr.stars:,} | [#{pr.number}]({pr.url}) {_md(pr.title)} |"
            for pr in newest
        ]
    ordered = [pr for prs in _by_repository(open_prs) for pr in prs]
    if ordered:
        lines += [
            "",
            f"#### In review ({len(ordered)})",
            "",
            "| Repository | Stars | Pull request |",
            "| --- | ---: | --- |",
        ]
        lines += [
            f"| {_md(pr.repo)} | {pr.stars:,} | [#{pr.number}]({pr.url}) {_md(pr.title)} |"
            for pr in ordered
        ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- files and outputs


def write(path: Path, content: str) -> None:
    """Write one card, leaving the file untouched when nothing changed."""
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        print(f"{path} unchanged")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {path} ({len(content):,} bytes)")


def set_outputs(target: str, values: dict[str, int]) -> None:
    """Append key=value lines to $GITHUB_OUTPUT when running inside Actions."""
    if target:
        with Path(target).open("a", encoding="utf-8") as fh:
            fh.writelines(f"{key}={value}\n" for key, value in values.items())


def keep_existing(paths: Iterable[Path], exc: Exception) -> int:
    """Handle a failed fetch: keep every earlier card, or fail when one is missing."""
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        print(
            f"::error::GitHub API request failed ({exc}) and there is no earlier "
            f"card to keep for {', '.join(missing)}."
        )
        return 1
    print(f"::warning::GitHub API request failed ({exc}); kept the existing cards.")
    return 0


def git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run one git command in the working directory, capturing its output."""
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def commit_cards(paths: Iterable[Path], message: str) -> int:
    """Commit the cards that changed as github-actions[bot] and push them; return the exit code.

    Only the card files go into the commit, even when other changes are staged.
    A rejected push (the branch moved during the run) is rebased and retried once.
    """
    if git("rev-parse", "--is-inside-work-tree").returncode:
        print(
            "::error::commit is true but the working directory is not a git checkout."
        )
        return 1
    branch = git("symbolic-ref", "--quiet", "--short", "HEAD")
    if branch.returncode:
        print(
            "::warning::commit is true but HEAD is detached, as on a pull_request "
            "run, so the cards were not committed."
        )
        return 0
    name = branch.stdout.strip()
    files = [str(p) for p in paths if p.is_file()]
    added = git("add", "--", *files)
    if added.returncode:
        print(f"::error::git add failed: {added.stderr.strip()}")
        return 1
    if not git("diff", "--cached", "--quiet", "--", *files).returncode:
        print("No card changed, so there is nothing to commit.")
        return 0
    identity = ("-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}")
    done = git(*identity, "commit", "--quiet", "-m", message, "--", *files)
    if done.returncode:
        print(f"::error::git commit failed: {(done.stderr or done.stdout).strip()}")
        return 1
    for attempt in range(2):
        pushed = git("push", "--quiet", "origin", f"HEAD:{name}")
        if not pushed.returncode:
            print(f"Committed the cards and pushed them to {name}.")
            return 0
        if attempt:
            break
        rebased = git("pull", "--rebase", "--autostash", "--quiet", "origin", name)
        if rebased.returncode:
            git("rebase", "--abort")
            print(
                f"::error::could not rebase the cards onto {name}: {rebased.stderr.strip()}"
            )
            return 1
    print(f"::error::could not push the cards to {name}: {pushed.stderr.strip()}")
    return 1


def main(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    try:
        config = load_config(env)
    except ConfigError as exc:
        print(f"::error::{exc}")
        return 1
    print(
        f"Searching pull requests by {config.username} to repositories they do not own"
    )
    try:
        merged = search_prs(config.username, "merged", config.token)
        open_prs = search_prs(config.username, "open", config.token)
    except FETCH_ERRORS as exc:
        return keep_existing(config.outputs.values(), exc)
    found = len(merged) + len(open_prs)
    keep = (
        config.username,
        config.exclude_owners,
        config.exclude_repos,
        config.min_stars,
    )
    merged = select_upstream(merged, *keep)
    open_prs = select_upstream(open_prs, *keep)
    cards = {
        "summary": render_summary(merged, open_prs, config.accent),
        "merged": render_merged(merged, config.max_rows),
        "review": render_review(open_prs, config.max_rows),
        "summary-mobile": render_summary_mobile(merged, open_prs, config.accent),
        "merged-mobile": render_merged_mobile(merged, config.max_rows),
        "review-mobile": render_review_mobile(open_prs, config.max_rows),
    }
    for card, path in config.outputs.items():
        write(path, cards[card])
    stats = summarize(merged, open_prs)
    print(
        f"{stats['merged']} merged and {stats['open']} in review across "
        f"{stats['projects']} projects with {stats['stars']:,} combined stars"
    )
    set_outputs(env.get("GITHUB_OUTPUT", ""), stats)
    if summary := env.get("GITHUB_STEP_SUMMARY", ""):
        left_out = found - len(merged) - len(open_prs)
        with Path(summary).open("a", encoding="utf-8") as fh:
            fh.write(step_summary(config.username, merged, open_prs, left_out))
    if config.commit:
        return commit_cards(config.outputs.values(), config.commit_message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
