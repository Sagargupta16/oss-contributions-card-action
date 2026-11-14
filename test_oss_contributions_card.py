"""Tests for oss_contributions_card.py. No network: fetch is monkeypatched."""

from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.error
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

import pytest

import flat_style
import oss_contributions_card as occ

SVG = "{http://www.w3.org/2000/svg}"
EN_DASH, EM_DASH = chr(0x2013), chr(0x2014)
SPARKLES, VS16, ROCKET = chr(0x2728), chr(0xFE0F), chr(0x1F680)


def node(
    repo: str,
    number: int,
    title: str = "Fix a bug",
    merged_at: str | None = "2026-09-01T00:00:00Z",
    stars: int = 10,
    private: bool = False,
) -> dict:
    return {
        "title": title,
        "number": number,
        "url": f"https://github.com/{repo}/pull/{number}",
        "mergedAt": merged_at,
        "repository": {
            "nameWithOwner": repo,
            "stargazerCount": stars,
            "isPrivate": private,
            "owner": {"login": repo.split("/", 1)[0]},
        },
    }


def pr(repo: str, number: int, **fields: object) -> occ.PullRequest:
    return occ.parse_node(node(repo, number, **fields))


def page(
    nodes: list[dict],
    cursor: str | None = None,
    more: bool = False,
    total: int | None = None,
) -> bytes:
    search = {
        "issueCount": len(nodes) if total is None else total,
        "pageInfo": {"hasNextPage": more, "endCursor": cursor},
        "nodes": nodes,
    }
    return json.dumps({"data": {"search": search}}).encode()


class FakeApi:
    """Answer each search from canned pages keyed by (state, cursor), recording every call."""

    def __init__(self, pages: dict[tuple[str, str | None], bytes]) -> None:
        self.pages = pages
        self.calls: list[dict] = []

    def __call__(self, url: str, body: dict, token: str, timeout: int = 30) -> bytes:
        variables = body["variables"]
        self.calls.append(variables)
        state = "merged" if "is:merged" in variables["q"] else "open"
        return self.pages[state, variables["after"]]


def list_rows(svg: str) -> list[tuple[str, ...]]:
    """Return (primary, secondary, meta) for every row of a list card."""
    root = ET.fromstring(svg)
    return [
        tuple(t.text or "" for t in g.iter(f"{SVG}text")) for g in root.iter(f"{SVG}g")
    ]


def raises(exc: Exception):
    def fetch(*args: object, **kwargs: object) -> bytes:
        raise exc

    return fetch


def returns(body: bytes):
    return lambda *args, **kwargs: body


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {
        "OSS_USERNAME": "alice",
        "GITHUB_TOKEN": "test-token",
        "OSS_EXCLUDE_OWNERS": "alice-org",
        "OSS_OUTPUT_SUMMARY": str(tmp_path / "assets" / "oss.svg"),
        "OSS_OUTPUT_MERGED": str(tmp_path / "assets" / "oss-merged.svg"),
        "OSS_OUTPUT_REVIEW": str(tmp_path / "assets" / "oss-review.svg"),
        "OSS_OUTPUT_SUMMARY_MOBILE": str(tmp_path / "assets" / "oss-mobile.svg"),
        "OSS_OUTPUT_MERGED_MOBILE": str(tmp_path / "assets" / "oss-merged-mobile.svg"),
        "OSS_OUTPUT_REVIEW_MOBILE": str(tmp_path / "assets" / "oss-review-mobile.svg"),
        "GITHUB_OUTPUT": str(tmp_path / "github_output"),
    }


CARD_KEYS = [name for _, name, _ in occ.OUTPUTS]


def live_api() -> FakeApi:
    return FakeApi(
        {
            ("merged", None): page(
                [node("psf/requests", 1, stars=52_000), node("alice-org/site", 2)]
            ),
            ("open", None): page(
                [node("pallets/flask", 3, merged_at=None, stars=69_000)]
            ),
        }
    )


# ---------------------------------------------------------------- search


def test_search_sends_the_documented_query(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi({("open", None): page([])})
    monkeypatch.setattr(occ, "fetch", api)

    occ.search_prs("alice", "open", "token")

    assert api.calls[0]["q"] == "is:pr author:alice is:open -user:alice"


def test_search_follows_the_cursor_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi(
        {
            ("merged", None): page([node("a/x", 1)], cursor="c1", more=True, total=2),
            ("merged", "c1"): page([node("b/y", 2)], total=2),
        }
    )
    monkeypatch.setattr(occ, "fetch", api)

    prs = occ.search_prs("alice", "merged", "token")

    assert [p.number for p in prs] == [1, 2]
    assert [c["after"] for c in api.calls] == [None, "c1"]


def test_search_drops_a_result_repeated_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi(
        {
            ("merged", None): page([node("a/x", 1)], cursor="c1", more=True),
            ("merged", "c1"): page([node("a/x", 1), node("a/x", 2)]),
        }
    )
    monkeypatch.setattr(occ, "fetch", api)

    prs = occ.search_prs("alice", "merged", "token")

    assert [p.number for p in prs] == [1, 2]


def test_search_stops_at_the_page_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def endless(url: str, body: dict, token: str, timeout: int = 30) -> bytes:
        calls.append(body)
        n = len(calls)
        return page([node("a/x", n)], cursor=f"c{n}", more=True, total=5000)

    monkeypatch.setattr(occ, "fetch", endless)

    prs = occ.search_prs("alice", "merged", "token")

    assert len(calls) == occ.MAX_PAGES
    assert len(prs) == occ.MAX_PAGES


def test_graphql_errors_raise_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"errors": [{"message": "API rate limit exceeded"}]}).encode()
    monkeypatch.setattr(occ, "fetch", returns(body))

    with pytest.raises(occ.ApiError, match="rate limit"):
        occ.search_prs("alice", "open", "token")


@pytest.mark.parametrize(
    "url",
    ["http://api.github.com/graphql", "https://api.github.com.evil.example/graphql"],
)
def test_fetch_refuses_urls_outside_the_allowlist(url: str) -> None:
    with pytest.raises(ValueError, match="refusing"):
        occ.fetch(url, {}, "token")


# ---------------------------------------------------------------- filtering and counts


def test_select_upstream_drops_own_and_excluded_owners() -> None:
    prs = [pr("Alice/dotfiles", 1), pr("ALICE-ORG/site", 2), pr("psf/requests", 3)]

    kept = occ.select_upstream(prs, "alice", {"alice-org"})

    assert [p.repo for p in kept] == ["psf/requests"]


def test_select_upstream_drops_private_repositories() -> None:
    prs = [pr("corp/secret", 1, private=True), pr("psf/requests", 2)]

    kept = occ.select_upstream(prs, "alice", set())

    assert [p.repo for p in kept] == ["psf/requests"]


def test_select_upstream_drops_an_excluded_repository() -> None:
    prs = [pr("lists/awesome", 1), pr("lists/tool", 2)]

    kept = occ.select_upstream(prs, "alice", set(), {"lists/awesome"})

    assert [p.repo for p in kept] == ["lists/tool"]


def test_select_upstream_drops_every_repository_of_a_wildcard_owner() -> None:
    prs = [pr("lists/awesome", 1), pr("lists/portfolios", 2), pr("psf/requests", 3)]

    kept = occ.select_upstream(prs, "alice", set(), {"lists/*"})

    assert [p.repo for p in kept] == ["psf/requests"]


def test_select_upstream_matches_excluded_repositories_case_insensitively() -> None:
    prs = [
        pr("FirstContributions/First-Contributions", 1),
        pr("Lists/Awesome", 2),
        pr("psf/requests", 3),
    ]

    kept = occ.select_upstream(
        prs, "alice", set(), {"firstcontributions/FIRST-contributions", "LISTS/*"}
    )

    assert [p.repo for p in kept] == ["psf/requests"]


def test_select_upstream_with_no_excluded_repositories_keeps_the_rest() -> None:
    prs = [pr("lists/awesome", 1), pr("psf/requests", 2)]

    kept = occ.select_upstream(prs, "alice", set(), set())

    assert [p.repo for p in kept] == ["lists/awesome", "psf/requests"]


def test_select_upstream_drops_repositories_below_min_stars() -> None:
    prs = [pr("tiny/list", 1, stars=3), pr("mid/tool", 2, stars=50), pr("a/b", 3)]

    kept = occ.select_upstream(prs, "alice", set(), set(), min_stars=50)

    assert [p.repo for p in kept] == ["mid/tool"]


def test_summarize_counts_projects_and_their_combined_stars() -> None:
    merged = [
        pr("big/framework", 1, stars=1000),
        pr("big/framework", 2, stars=1000),
        pr("small/lib", 3, stars=5),
    ]
    open_prs = [pr("other/repo", 9, merged_at=None, stars=99)]

    stats = occ.summarize(merged, open_prs)

    assert stats == {"merged": 3, "open": 1, "projects": 2, "stars": 1005}


# ---------------------------------------------------------------- cards


def test_summary_ranks_project_chips_by_stars() -> None:
    merged = [
        pr("small/lib", 1, stars=40),
        pr("big/framework", 2, stars=120_000),
        pr("big/framework", 3, stars=120_000),
        pr("mid/tool", 4, stars=2_500),
    ]

    root = ET.fromstring(occ.render_summary(merged, []))

    chips = [
        t.text for t in root.iter(f"{SVG}text") if t.get("text-anchor") == "middle"
    ]
    assert chips == ["big/framework  x2  120.0K", "mid/tool  2.5K", "small/lib  40"]


def test_summary_ends_on_a_more_chip_when_projects_overflow() -> None:
    merged = [pr(f"owner{n}/project-{n}", n, stars=1000 + n) for n in range(40)]

    root = ET.fromstring(occ.render_summary(merged, []))

    chips = [
        t.text for t in root.iter(f"{SVG}text") if t.get("text-anchor") == "middle"
    ]
    hidden = int(chips[-1].removeprefix("+").removesuffix(" more"))
    assert chips[-1] == f"+{hidden} more"
    assert len(chips) - 1 + hidden == 40


def test_summary_chips_show_millions_of_stars_as_m() -> None:
    root = ET.fromstring(occ.render_summary([pr("huge/os", 1, stars=1_234_567)], []))

    chips = [
        t.text for t in root.iter(f"{SVG}text") if t.get("text-anchor") == "middle"
    ]
    assert chips == ["huge/os  1.2M"]


def test_accent_recolors_the_summary_card() -> None:
    svg = occ.render_summary([pr("a/x", 1)], [], accent="#a78bfa")

    assert 'fill="#a78bfa"' in svg
    assert 'stroke="#a78bfa44"' in svg
    assert occ.BLUE_LIGHT not in svg
    assert occ.SKY not in svg


def test_review_card_groups_pull_requests_by_repository() -> None:
    open_prs = [
        pr("b/two", 7, title="Solo", merged_at=None),
        pr("a/one", 12, title="Third", merged_at=None),
        pr("a/one", 3, title="First", merged_at=None),
        pr("a/one", 5, title="Second", merged_at=None),
    ]

    rows = list_rows(occ.render_review(open_prs, max_rows=12))

    assert rows == [
        ("a/one", "First; Second; Third", "#3, #5, #12"),
        ("b/two", "Solo", "#7"),
    ]


def test_review_card_caps_the_numbers_listed_per_repository() -> None:
    open_prs = [pr("a/one", n, merged_at=None) for n in range(1, 8)]

    rows = list_rows(occ.render_review(open_prs, max_rows=12))

    assert rows[0][2] == "#1, #2, #3, #4, +3"


def test_merged_card_lists_newest_first() -> None:
    merged = [
        pr("a/x", 1, merged_at="2026-01-01T00:00:00Z"),
        pr("b/y", 2, merged_at="2026-03-01T00:00:00Z"),
        pr("c/z", 3, merged_at="2026-02-01T00:00:00Z"),
    ]

    rows = list_rows(occ.render_merged(merged, max_rows=12))

    assert [meta for _, _, meta in rows] == ["#2", "#3", "#1"]


def test_merged_card_stops_at_max_rows_and_says_how_many_are_hidden() -> None:
    merged = [
        pr("a/x", n, merged_at=f"2026-01-{n:02d}T00:00:00Z") for n in range(1, 16)
    ]

    svg = occ.render_merged(merged, max_rows=12)

    assert len(list_rows(svg)) == 12
    assert "15 MERGED UPSTREAM" in svg
    assert "+3 more merged pull requests" in svg


def test_empty_results_render_friendly_cards() -> None:
    summary = occ.render_summary([], [])
    merged = occ.render_merged([], max_rows=12)
    review = occ.render_review([], max_rows=12)

    assert "NO MERGED PULL REQUESTS YET" in summary
    assert list_rows(merged)[0][0] == "No merged pull requests yet"
    assert list_rows(review)[0][0] == "No pull requests in review"


# ---------------------------------------------------------------- phone cards


def texts(svg: str) -> list[str]:
    """Return every text line of a card, in drawing order."""
    return [t.text or "" for t in ET.fromstring(svg).iter(f"{SVG}text")]


def test_phone_summary_shows_the_four_counts_and_ranked_chips() -> None:
    merged = [
        pr("small/lib", 1, stars=40),
        pr("big/framework", 2, stars=120_000),
        pr("big/framework", 3, stars=120_000),
    ]
    open_prs = [pr("other/repo", 9, merged_at=None)]

    lines = texts(occ.render_summary_mobile(merged, open_prs))

    # a tile label can wrap onto two lines, so compare the words in order
    tiles = " ".join(lines[1:-3])
    assert tiles == (
        "3 Merged upstream 1 In review 2 Projects contributed to 120K+ Combined stars"
    )
    assert lines[-3:] == ["MERGED INTO", "big/framework x2 120.0K", "small/lib 40"]


def test_phone_summary_caps_the_chips_with_a_more_chip() -> None:
    merged = [pr(f"o{n}/p{n}", n, stars=100 + n) for n in range(20)]

    lines = texts(occ.render_summary_mobile(merged, []))

    assert lines[-1] == f"+{20 - occ.PHONE_CHIPS} more"
    assert len([t for t in lines if t.startswith("o")]) == occ.PHONE_CHIPS


def test_phone_merged_card_lists_the_newest_with_dates_and_a_footer() -> None:
    merged = [
        pr("a/x", n, merged_at=f"2026-01-{n:02d}T00:00:00Z") for n in range(1, 10)
    ]

    lines = texts(occ.render_merged_mobile(merged, max_rows=12))

    assert lines[0] == "9 MERGED UPSTREAM | NEWEST FIRST"
    assert lines[2] == "PR #9 | 2026-01-09"
    assert len([t for t in lines if t.startswith("PR #")]) == occ.PHONE_MERGED_ROWS
    assert lines[-1] == f"+{9 - occ.PHONE_MERGED_ROWS} more merged pull requests"


def test_phone_cards_never_show_more_rows_than_max_rows() -> None:
    merged = [pr("a/x", n) for n in range(1, 10)]
    open_prs = [pr(f"r{n}/x", n, merged_at=None) for n in range(1, 10)]

    merged_lines = texts(occ.render_merged_mobile(merged, max_rows=2))
    review_lines = texts(occ.render_review_mobile(open_prs, max_rows=2))

    assert len([t for t in merged_lines if t.startswith("PR #")]) == 2
    assert merged_lines[-1] == "+7 more merged pull requests"
    assert review_lines[-1] == "+7 more pull requests in review"


def test_phone_review_card_groups_pull_requests_by_repository() -> None:
    open_prs = [
        pr("b/two", 7, title="Solo", merged_at=None),
        pr("a/one", 5, title="Second", merged_at=None),
        pr("a/one", 3, title="First", merged_at=None),
    ]

    lines = texts(occ.render_review_mobile(open_prs, max_rows=12))

    assert lines == [
        "3 PRS IN REVIEW",
        "a/one",
        "#3, #5",
        "First; Second",
        "b/two",
        "#7",
        "Solo",
    ]


def test_phone_cards_wrap_long_text_inside_the_card() -> None:
    title = "Add a very long descriptive title " * 4
    repo = "an-organization-with-a-long-name/a-repository-with-an-even-longer-name"
    merged = [pr(repo, 1, title=title.strip(), stars=2_000)]

    for svg in (
        occ.render_summary_mobile(merged, []),
        occ.render_merged_mobile(merged, max_rows=12),
    ):
        root = ET.fromstring(svg)
        for t in root.iter(f"{SVG}text"):
            mono = t.get("font-family") is not None
            right = float(t.get("x")) + occ.text_width(
                t.text, float(t.get("font-size")), mono
            )
            assert right <= occ.PHONE_W - occ.PHONE_PAD + 1, t.text


def test_phone_card_height_grows_with_its_rows() -> None:
    one = ET.fromstring(occ.render_merged_mobile([pr("a/x", 1)], max_rows=12))
    three = ET.fromstring(
        occ.render_merged_mobile([pr("a/x", n) for n in range(3)], max_rows=12)
    )

    assert int(three.get("height")) > int(one.get("height"))
    assert three.get("viewBox") == f"0 0 320 {three.get('height')}"


SAMPLE_MERGED = [
    pr("psf/requests", 1, stars=52_000),
    pr("pallets/flask", 2, stars=69_000),
]
SAMPLE_OPEN = [pr("pallets/flask", 3, merged_at=None, stars=69_000)]


@pytest.mark.parametrize(
    ("merged", "open_prs"),
    [([], []), (SAMPLE_MERGED, SAMPLE_OPEN)],
    ids=["empty", "full"],
)
def test_every_card_is_valid_self_contained_svg(
    merged: list[occ.PullRequest], open_prs: list[occ.PullRequest]
) -> None:
    cards = [
        (occ.render_summary(merged, open_prs), "840"),
        (occ.render_merged(merged, max_rows=12), "840"),
        (occ.render_review(open_prs, max_rows=12), "840"),
        (occ.render_summary_mobile(merged, open_prs), "320"),
        (occ.render_merged_mobile(merged, max_rows=12), "320"),
        (occ.render_review_mobile(open_prs, max_rows=12), "320"),
    ]

    for svg, width in cards:
        root = ET.fromstring(svg)
        assert root.tag == f"{SVG}svg"
        assert root.get("width") == width
        assert root.get("role") == "img"
        assert root.get("aria-label")
        assert "<script" not in svg
        assert "href" not in svg


def test_titles_are_escaped() -> None:
    title = 'Fix <script> & "quotes"'

    svg = occ.render_merged([pr("a/x", 1, title=title)], max_rows=12)

    assert "<script>" not in svg
    assert "Fix &lt;script&gt; &amp; &quot;quotes&quot;" in svg
    assert list_rows(svg)[0][1] == title


def test_titles_lose_dashes_and_emoji() -> None:
    title = (
        f"feat: faster {EN_DASH} safer {EM_DASH} smaller {SPARKLES}{VS16}{ROCKET} build"
    )

    parsed = pr("a/x", 1, title=title)

    assert parsed.title == "feat: faster - safer - smaller build"


def test_titles_lose_characters_xml_cannot_hold() -> None:
    parsed = pr("a/x", 1, title="bad\x00\x1b byte")

    svg = occ.render_merged([parsed], max_rows=12)

    assert parsed.title == "bad byte"
    ET.fromstring(svg)


# ---------------------------------------------------------------- config


@pytest.mark.parametrize("username", ["", "alice is:open", "alice -user:bob", "-alice"])
def test_config_rejects_a_username_that_is_not_a_login(
    env: dict[str, str], username: str
) -> None:
    env["OSS_USERNAME"] = username

    with pytest.raises(occ.ConfigError, match="username"):
        occ.load_config(env)


def test_config_requires_a_token(env: dict[str, str]) -> None:
    del env["GITHUB_TOKEN"]

    with pytest.raises(occ.ConfigError, match="token"):
        occ.load_config(env)


@pytest.mark.parametrize("max_rows", ["0", "-1", "ten", "1.5"])
def test_config_rejects_max_rows_that_is_not_a_positive_number(
    env: dict[str, str], max_rows: str
) -> None:
    env["OSS_MAX_ROWS"] = max_rows

    with pytest.raises(occ.ConfigError, match="max-rows"):
        occ.load_config(env)


@pytest.mark.parametrize("accent", ["blue", "#12345", '#abc" onload="x'])
def test_config_rejects_an_accent_that_is_not_a_hex_color(
    env: dict[str, str], accent: str
) -> None:
    env["OSS_ACCENT"] = accent

    with pytest.raises(occ.ConfigError, match="accent"):
        occ.load_config(env)


def test_config_expands_a_short_accent(env: dict[str, str]) -> None:
    env["OSS_ACCENT"] = "#ABC"

    assert occ.load_config(env).accent == "#aabbcc"


@pytest.mark.parametrize(
    "value", ["", "   ", " , ,"], ids=["empty", "spaces", "commas"]
)
def test_config_reads_an_empty_exclude_repos_as_no_exclusions(
    env: dict[str, str], value: str
) -> None:
    env["OSS_EXCLUDE_REPOS"] = value

    assert occ.load_config(env).exclude_repos == frozenset()


def test_config_reads_exclude_repos_entries(env: dict[str, str]) -> None:
    env["OSS_EXCLUDE_REPOS"] = " firstcontributions/first-contributions , is-a-dev/* "

    config = occ.load_config(env)

    assert config.exclude_repos == {
        "firstcontributions/first-contributions",
        "is-a-dev/*",
    }


@pytest.mark.parametrize(
    "entry", ["firstcontributions", "a/b/c", "a/", "/b", "a b/c", "*/b"]
)
def test_config_rejects_an_exclude_repos_entry_that_is_not_owner_slash_repo(
    env: dict[str, str], entry: str
) -> None:
    env["OSS_EXCLUDE_REPOS"] = f"psf/requests,{entry}"

    with pytest.raises(occ.ConfigError, match="exclude-repos"):
        occ.load_config(env)


@pytest.mark.parametrize("min_stars", ["-1", "ten", "1.5"])
def test_config_rejects_min_stars_that_is_not_a_whole_number(
    env: dict[str, str], min_stars: str
) -> None:
    env["OSS_MIN_STARS"] = min_stars

    with pytest.raises(occ.ConfigError, match="min-stars"):
        occ.load_config(env)


def test_config_reads_min_stars_and_defaults_to_zero(env: dict[str, str]) -> None:
    assert occ.load_config(env).min_stars == 0
    env["OSS_MIN_STARS"] = " 100 "
    assert occ.load_config(env).min_stars == 100


@pytest.mark.parametrize("commit", ["yes", "1", "on"])
def test_config_rejects_commit_that_is_not_true_or_false(
    env: dict[str, str], commit: str
) -> None:
    env["OSS_COMMIT"] = commit

    with pytest.raises(occ.ConfigError, match="commit"):
        occ.load_config(env)


def test_config_reads_commit_and_its_message(env: dict[str, str]) -> None:
    assert occ.load_config(env).commit is False
    env["OSS_COMMIT"] = "TRUE"
    env["OSS_COMMIT_MESSAGE"] = "  "
    config = occ.load_config(env)
    assert config.commit is True
    assert config.commit_message == occ.COMMIT_MESSAGE


# ---------------------------------------------------------------- step summary


def test_step_summary_lists_every_pull_request_with_escaped_titles() -> None:
    merged = [pr("psf/requests", 1, title="Fix | pipes and *stars*", stars=52_000)]
    open_prs = [pr("pallets/flask", 3, title="Open one", merged_at=None, stars=69_000)]

    md = occ.step_summary("alice", merged, open_prs, left_out=2)

    assert "| 1 | 1 | 1 | 52,000 |" in md
    assert "2 pull requests left out" in md
    assert (
        "| 2026-09-01 | psf/requests | 52,000 | [#1](https://github.com/psf/requests/pull/1)"
        " Fix \\| pipes and \\*stars\\* |"
    ) in md
    assert (
        "| pallets/flask | 69,000 | [#3](https://github.com/pallets/flask/pull/3) Open one |"
        in md
    )


def test_main_writes_the_step_summary(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(occ, "fetch", live_api())
    env["GITHUB_STEP_SUMMARY"] = str(tmp_path / "step_summary.md")

    assert occ.main(env) == 0

    md = Path(env["GITHUB_STEP_SUMMARY"]).read_text(encoding="utf-8")
    assert md.startswith("### Open source contributions by @alice")
    assert "1 pull request left out" in md  # alice-org/site, an excluded owner
    assert "#### Merged (1)" in md
    assert "#### In review (1)" in md


# ---------------------------------------------------------------- main


def test_main_writes_the_cards_and_the_outputs(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(occ, "fetch", live_api())

    code = occ.main(env)

    assert code == 0
    for key in CARD_KEYS:
        ET.parse(env[key])
    outputs = Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8").splitlines()
    assert outputs == ["merged=1", "open=1", "projects=1", "stars=52000"]


def test_main_skips_a_card_whose_output_path_is_empty(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(occ, "fetch", live_api())
    review = Path(env["OSS_OUTPUT_REVIEW"])
    env["OSS_OUTPUT_REVIEW"] = ""

    code = occ.main(env)

    assert code == 0
    assert Path(env["OSS_OUTPUT_SUMMARY"]).is_file()
    assert not review.exists()


def test_main_leaves_excluded_repositories_out_of_every_card_and_output(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(occ, "fetch", live_api())
    env["OSS_EXCLUDE_REPOS"] = "PSF/Requests, pallets/*"

    code = occ.main(env)

    assert code == 0
    outputs = Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8").splitlines()
    assert outputs == ["merged=0", "open=0", "projects=0", "stars=0"]
    cards = [Path(env[k]).read_text(encoding="utf-8") for k in CARD_KEYS]
    assert not any("psf/requests" in c or "pallets/flask" in c for c in cards)


FAILURES = {
    "offline": raises(urllib.error.URLError("network is unreachable")),
    "http-502": raises(
        urllib.error.HTTPError(occ.API_URL, 502, "Bad Gateway", {}, None)
    ),
    "not-json": returns(b"<html>unicorn</html>"),
    "graphql-error": returns(
        json.dumps({"errors": [{"message": "rate limited"}]}).encode()
    ),
    "no-search": returns(json.dumps({"data": {"search": None}}).encode()),
}


@pytest.mark.parametrize("failure", FAILURES.values(), ids=FAILURES.keys())
def test_api_failure_keeps_the_existing_cards(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch, failure: object
) -> None:
    cards = [Path(env[k]) for k in CARD_KEYS]
    for path in cards:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(occ, "fetch", failure)

    code = occ.main(env)

    assert code == 0
    assert [p.read_text(encoding="utf-8") for p in cards] == ["<svg/>"] * 6
    assert not Path(env["GITHUB_OUTPUT"]).exists()


def test_api_failure_with_no_earlier_cards_exits_1(
    env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(occ, "fetch", FAILURES["offline"])

    code = occ.main(env)

    assert code == 1
    assert "no earlier card to keep" in capsys.readouterr().out


def test_output_never_contains_the_token(
    env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(occ, "fetch", FAILURES["graphql-error"])
    occ.main(env)
    monkeypatch.setattr(occ, "fetch", live_api())
    occ.main(env)

    assert env["GITHUB_TOKEN"] not in capsys.readouterr().out


def test_main_drops_repositories_below_min_stars(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(occ, "fetch", live_api())
    env["OSS_MIN_STARS"] = "60000"

    assert occ.main(env) == 0

    outputs = Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8").splitlines()
    assert outputs == ["merged=0", "open=1", "projects=0", "stars=0"]


# ---------------------------------------------------------------- commit


def run_git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a clone of a local bare remote with one commit on main, as the working directory."""
    config = tmp_path / "gitconfig"
    config.write_text(
        "[user]\n\tname = Test\n\temail = test@example.com\n"
        "[init]\n\tdefaultBranch = main\n",
        encoding="utf-8",
    )
    # keep the developer's own git config (signing, autocrlf) out of the test
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    remote = tmp_path / "remote.git"
    run_git(tmp_path, "init", "--quiet", "--bare", str(remote))
    work = tmp_path / "work"
    run_git(tmp_path, "clone", "--quiet", str(remote), str(work))
    (work / "README.md").write_text("cards\n", encoding="utf-8")
    run_git(work, "add", "README.md")
    run_git(work, "commit", "--quiet", "-m", "init")
    run_git(work, "push", "--quiet", "origin", "HEAD:main")
    monkeypatch.chdir(work)
    return work


def card(work: Path, name: str = "oss.svg", content: str = "<svg/>") -> Path:
    path = work / "assets" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_commit_pushes_only_the_cards_as_the_actions_bot(checkout: Path) -> None:
    cards = [card(checkout), card(checkout, "oss-mobile.svg")]
    (checkout / "notes.txt").write_text("not a card", encoding="utf-8")
    run_git(checkout, "add", "notes.txt")

    code = occ.commit_cards(cards, "chore: refresh cards")

    assert code == 0
    assert run_git(checkout, "log", "-1", "--format=%an|%s", "origin/main") == (
        "github-actions[bot]|chore: refresh cards"
    )
    files = run_git(checkout, "show", "--name-only", "--format=", "origin/main")
    assert files.splitlines() == ["assets/oss-mobile.svg", "assets/oss.svg"]


def test_commit_does_nothing_when_no_card_changed(checkout: Path) -> None:
    cards = [card(checkout)]
    assert occ.commit_cards(cards, "first") == 0
    before = run_git(checkout, "rev-parse", "origin/main")

    assert occ.commit_cards(cards, "second") == 0

    assert run_git(checkout, "rev-parse", "origin/main") == before


def test_commit_skips_a_detached_head(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_git(checkout, "checkout", "--quiet", "--detach")
    before = run_git(checkout, "rev-parse", "origin/main")

    assert occ.commit_cards([card(checkout)], "msg") == 0

    assert "HEAD is detached" in capsys.readouterr().out
    assert run_git(checkout, "rev-parse", "origin/main") == before


def test_commit_rebases_when_the_branch_moved_during_the_run(
    checkout: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    run_git(tmp_path, "clone", "--quiet", str(tmp_path / "remote.git"), str(other))
    (other / "README.md").write_text("edited elsewhere\n", encoding="utf-8")
    run_git(other, "commit", "--quiet", "-am", "edit readme")
    run_git(other, "push", "--quiet", "origin", "HEAD:main")

    assert occ.commit_cards([card(checkout)], "chore: refresh cards") == 0

    subjects = run_git(checkout, "log", "--format=%s", "origin/main").splitlines()
    assert subjects == ["chore: refresh cards", "edit readme", "init"]


def test_commit_outside_a_git_checkout_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "plain"
    outside.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))

    assert occ.commit_cards([card(outside)], "msg") == 1


def test_main_commits_the_cards_when_commit_is_true(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch, checkout: Path
) -> None:
    monkeypatch.setattr(occ, "fetch", live_api())
    for _, name, default in occ.OUTPUTS:
        env[name] = default  # relative paths inside the checkout
    env["OSS_COMMIT"] = "true"

    assert occ.main(env) == 0

    files = run_git(checkout, "show", "--name-only", "--format=", "origin/main")
    assert sorted(files.splitlines()) == sorted(d for _, _, d in occ.OUTPUTS)


# ---------------------------------------------------------------- style

# What v1.1.0 writes for live_api(), so the default style stays byte-identical
# for everyone already on @v1.
CLASSIC_SHA256 = {
    "OSS_OUTPUT_SUMMARY": "1f08b5ccf8829c349beefdae1a09ff35b93fc354dce6b7e8c1d21f71aa0a398e",
    "OSS_OUTPUT_MERGED": "1d1daa2502846d5c9a98a1f1df96d31d25324a449ce83a544113d0ba3930ee06",
    "OSS_OUTPUT_REVIEW": "f3e323fadf012f908aa991b95b7993ce280a0cce387519fa75edf1a826ba7b10",
    "OSS_OUTPUT_SUMMARY_MOBILE": "6bb19e2377294e371fe04ad6b8a0923262a756b1b6e8c68e7dfbf00af9ee08e7",
    "OSS_OUTPUT_MERGED_MOBILE": "3dfe087923ee89e22c51e9ac60e98a6a789b22824124d9d7db54835463180008",
    "OSS_OUTPUT_REVIEW_MOBILE": "a0628600116465b34966cb9097bfe609f08ae7c7ae48ef11b07d75d7141ef4e9",
}
FLAT_KEYS = (
    "OSS_OUTPUT_SUMMARY",
    "OSS_OUTPUT_REVIEW",
    "OSS_OUTPUT_SUMMARY_MOBILE",
    "OSS_OUTPUT_REVIEW_MOBILE",
)


@pytest.mark.parametrize(
    "style", [None, "classic", " Classic "], ids=["unset", "classic", "spaced"]
)
def test_classic_style_writes_the_same_bytes_as_v1_1_0(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch, style: str | None
) -> None:
    monkeypatch.setattr(occ, "fetch", live_api())
    if style is not None:
        env["OSS_STYLE"] = style

    assert occ.main(env) == 0

    for name, digest in CLASSIC_SHA256.items():
        assert hashlib.sha256(Path(env[name]).read_bytes()).hexdigest() == digest, name


def test_config_reads_the_style_and_rejects_anything_else(env: dict[str, str]) -> None:
    assert occ.load_config(env).style == "classic"
    env["OSS_STYLE"] = " FLAT "
    assert occ.load_config(env).style == "flat"
    env["OSS_STYLE"] = "dark"
    with pytest.raises(occ.ConfigError, match="style"):
        occ.load_config(env)


def test_flat_style_has_no_merged_card(env: dict[str, str]) -> None:
    env["OSS_STYLE"] = "flat"

    assert set(occ.load_config(env).outputs) == set(occ.FLAT_CARDS)


def test_main_with_flat_style_writes_four_cards_and_the_same_outputs(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(occ, "fetch", live_api())
    env["OSS_STYLE"] = "flat"

    assert occ.main(env) == 0

    for key in FLAT_KEYS:
        ET.parse(env[key])
    assert not Path(env["OSS_OUTPUT_MERGED"]).exists()
    assert not Path(env["OSS_OUTPUT_MERGED_MOBILE"]).exists()
    summary = texts(Path(env["OSS_OUTPUT_SUMMARY"]).read_text(encoding="utf-8"))
    assert summary[0] == "FIRST MERGE 2026-09-01"
    assert summary[1].startswith("UPDATED 20")
    outputs = Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8").splitlines()
    assert outputs == ["merged=1", "open=1", "projects=1", "stars=52000"]


def test_flat_api_failure_keeps_the_four_cards(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    env["OSS_STYLE"] = "flat"
    kept = [Path(env[key]) for key in FLAT_KEYS]
    for path in kept:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(occ, "fetch", FAILURES["offline"])

    assert occ.main(env) == 0  # no merged card has to exist to keep the rest

    assert [p.read_text(encoding="utf-8") for p in kept] == ["<svg/>"] * 4


FLAT_MERGED = [
    pr("psf/requests", 11, merged_at="2026-01-05T00:00:00Z", stars=52_000),
    pr("psf/requests", 12, merged_at="2026-02-05T00:00:00Z", stars=52_000),
    pr("pallets/flask", 21, merged_at="2026-03-05T00:00:00Z", stars=69_000),
    pr("encode/httpx", 31, merged_at="2026-04-05T00:00:00Z", stars=13_000),
    pr("fastapi/typer", 41, merged_at="2026-05-05T00:00:00Z", stars=16_000),
    pr("pydantic/pydantic", 51, merged_at="2026-06-05T00:00:00Z", stars=21_000),
    pr("astral-sh/ruff", 61, merged_at="2026-07-05T00:00:00Z", stars=40_000),
    pr("pytest-dev/pytest", 71, merged_at="2026-08-05T00:00:00Z", stars=12_000),
    pr("python/cpython", 81, merged_at="2026-09-05T00:00:00Z", stars=65_000),
]
FLAT_OPEN = [
    pr("python/cpython", 90, merged_at=None, stars=65_000),
    pr("small/tool", 93, merged_at=None, stars=0),
    pr("astral-sh/ruff", 92, merged_at=None, stars=40_000),
    pr("python/cpython", 91, merged_at=None, stars=65_000),
]
LONG_REPO = "an-organization-with-a-long-name/a-repository-with-an-even-longer-name"
FLAT_CASES = {
    "empty": ([], []),
    "one": (FLAT_MERGED[-1:], FLAT_OPEN[:1]),
    "two": (FLAT_MERGED[-2:], FLAT_OPEN[:2]),
    "four": (FLAT_MERGED[-4:], FLAT_OPEN),
    "five": (FLAT_MERGED[-5:], FLAT_OPEN),
    "full": (FLAT_MERGED, FLAT_OPEN),
    "long": (
        [
            pr(
                LONG_REPO,
                12345,
                title="Add a very long descriptive title " * 4,
                stars=1_234_567,
            ),
            *FLAT_MERGED,
        ],
        [pr(f"{LONG_REPO}-{n}", n, merged_at=None, stars=n) for n in range(12)],
    ),
}


def flat(
    merged: list[occ.PullRequest], open_prs: list[occ.PullRequest], max_rows: int = 12
) -> dict[str, str]:
    return occ.render_flat(merged, open_prs, max_rows, "2026-11-14")


def flat_cards() -> Iterator[tuple[str, str, str]]:
    """(case, card, svg) for every flat card of every case."""
    for case, (merged, open_prs) in FLAT_CASES.items():
        for card_name, svg in flat(merged, open_prs).items():
            yield case, card_name, svg


def test_flat_cards_are_840_and_320_wide_and_self_contained() -> None:
    for case, card_name, svg in flat_cards():
        root = ET.fromstring(svg)
        width = "320" if card_name.endswith("mobile") else "840"
        assert root.get("width") == width, (case, card_name)
        assert root.get("viewBox") == f"0 0 {width} {root.get('height')}"
        assert root.get("role") == "img" and root.get("aria-label")
        for banned in ("<script", "href", "<image", "@import", "url(http"):
            assert banned not in svg, (case, card_name, banned)


def test_flat_cards_have_no_gradient_glow_shine_or_reduced_motion() -> None:
    for case, card_name, svg in flat_cards():
        for banned in ("Gradient", "filter", "blur", "shine", "prefers-reduced-motion"):
            assert banned not in svg, (case, card_name, banned)


def test_flat_cards_are_poster_safe() -> None:
    """A still render shows the whole card: no delayed begin, and nothing hidden at rest but a loop's turn."""
    for case, card_name, svg in flat_cards():
        root = ET.fromstring(svg)
        assert 'begin="' not in svg, (case, card_name)
        for element in root.iter():
            if element.get("opacity") == "0":
                loops = [a for a in element if a.get("repeatCount") == "indefinite"]
                assert loops, (case, card_name, element.tag)
        for animation in root.iter(f"{SVG}animate"):
            if animation.get("repeatCount") is None:
                assert animation.get("fill") == "freeze", (case, card_name)
                assert animation.get("keyTimes").startswith("0;"), (case, card_name)


def test_flat_loops_run_on_the_page_clock() -> None:
    for case, card_name, svg in flat_cards():
        for element in ET.fromstring(svg).iter():
            if element.get("repeatCount") == "indefinite":
                seconds = float(element.get("dur").removesuffix("s"))
                assert seconds in flat_style.CLOCK, (case, card_name, seconds)


def test_flat_text_holds_the_size_floor() -> None:
    for case, card_name, svg in flat_cards():
        phone = card_name.endswith("mobile")
        micro = flat_style.MICRO_PHONE if phone else flat_style.MICRO
        for t in ET.fromstring(svg).iter(f"{SVG}text"):
            size = float(t.get("font-size"))
            assert size >= micro, (case, card_name, t.text, size)
            if t.get("class") == "m":  # a mono micro-label
                assert size == micro, (case, card_name, t.text, size)


def test_flat_phone_text_stays_inside_the_card() -> None:
    for case, card_name, svg in flat_cards():
        if not card_name.endswith("mobile"):
            continue
        for t in ET.fromstring(svg).iter(f"{SVG}text"):
            size, cls = float(t.get("font-size")), t.get("class")
            width = flat_style._width(t.text, size, cls)
            x = float(t.get("x"))
            left = {"end": x - width, "middle": x - width / 2}.get(
                t.get("text-anchor"), x
            )
            assert left >= flat_style.PHONE_PAD - 1, (case, t.text)
            assert left + width <= 320 - flat_style.PHONE_PAD + 1, (case, t.text)


def test_flat_summary_shows_the_tiles_the_newest_six_and_the_rest() -> None:
    svg = flat(FLAT_MERGED, FLAT_OPEN)["summary"]

    lines = texts(svg)

    assert lines[:2] == ["FIRST MERGE 2026-01-05", "UPDATED 2026-11-14"]
    assert lines[2:10] == [
        "9",
        "MERGED UPSTREAM",
        "8",
        "REPOS WITH MERGES",
        "288K+",
        "COMBINED STARS",
        "4",
        "OPEN PRS",
    ]
    assert lines[10:14] == ["python/cpython", "#81", "2026-09-05", "65K"]
    assert lines[lines.index("ALSO MERGED INTO") + 1 :] == [
        "pallets/flask",
        "69K",
        "psf/requests",
        "52K",
        f"+3 more pull requests on GitHub {flat_style.ARROW}",
    ]
    # green marks the newest merge only, and amber stays on the review card
    assert flat_style.GREEN in svg and flat_style.AMBER not in svg


def test_flat_phone_summary_lists_the_newest_six() -> None:
    lines = texts(flat(FLAT_MERGED, FLAT_OPEN)["summary-mobile"])

    metas = [t for t in lines if t.startswith("#")]
    assert metas[:2] == ["#81  2026-09-05", "#71  2026-08-05"]
    assert len(metas) == flat_style.MERGED_SHOWN
    assert f"+3 more pull requests on GitHub {flat_style.ARROW}" in lines
    assert lines[-1] == "UPDATED 2026-11-14"


def test_flat_review_lists_repositories_with_their_counts() -> None:
    cards = flat(FLAT_MERGED, FLAT_OPEN)

    assert texts(cards["review"]) == [
        "3 REPOSITORIES",
        "IN REVIEW",
        "python/cpython",
        "2",
        "65K",
        "astral-sh/ruff",
        "40K",
        "small/tool",
    ]
    assert texts(cards["review-mobile"]) == [
        "3 REPOSITORIES",
        "IN REVIEW",
        "python/cpython",
        "65K",
        "2",
        "astral-sh/ruff",
        "40K",
        "small/tool",
    ]
    assert (
        flat_style.AMBER in cards["review"] and flat_style.GREEN not in cards["review"]
    )


def test_flat_max_rows_caps_the_ledger_and_the_review_repositories() -> None:
    cards = flat(FLAT_MERGED, FLAT_OPEN, max_rows=2)

    assert f"+7 more pull requests on GitHub {flat_style.ARROW}" in texts(
        cards["summary"]
    )
    assert texts(cards["review"])[-1] == "+1 more"
    assert texts(cards["review-mobile"])[-1] == "+1 more"


def test_flat_alt_text_names_every_repository() -> None:
    cards = flat(FLAT_MERGED, FLAT_OPEN)

    summary = ET.fromstring(cards["summary"]).get("aria-label")
    review = ET.fromstring(cards["review"]).get("aria-label")

    assert summary.startswith(
        "Open source: 9 pull requests merged upstream into 8 repositories with 288K+ "
        "combined stars, and 4 pull requests open. Merged into, most starred first: "
        "pallets/flask, python/cpython, psf/requests,"
    )
    assert summary.endswith(
        "The 6 newest merges are listed, with 3 more pull requests on GitHub."
    )
    assert review == (
        "4 pull requests in review upstream: python/cpython (2), astral-sh/ruff, small/tool."
    )


def test_flat_empty_results_render_friendly_cards() -> None:
    cards = flat([], [])

    assert "NO MERGES YET" in texts(cards["summary"])
    assert "NO MERGES YET" in texts(cards["summary-mobile"])
    assert texts(cards["review"]) == ["NO OPEN PRS"]
    assert texts(cards["review-mobile"]) == ["NO OPEN PRS"]


def test_flat_titles_are_escaped() -> None:
    merged = [pr("a/x", 1, title='Fix <script> & "quotes"')]

    for svg in flat(merged, []).values():
        assert "<script>" not in svg
        ET.fromstring(svg)
    assert "Fix &lt;script&gt; &amp; &quot;quotes&quot;" in flat(merged, [])["summary"]
