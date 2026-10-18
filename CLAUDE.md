# CLAUDE.md

> This file stacks on top of the workspace root at `C:\Code\GitHub\`:
> - Root [`CLAUDE.md`](../../CLAUDE.md) -- voice, rules, routing map, references, skills, slash commands, conventions.
> - Root [`MEMORY.md`](../../MEMORY.md) -- live facts across repos.
> - Root [`STATUS.md`](../../STATUS.md) -- live PR/CI/security dashboard.
> - [`.claude/resources/`](../../.claude/resources/README.md) -- deep reference for collaboration, workflow, git, OSS, debugging, voice.
>
> Read those first. The guidance below only adds **repo-specific context** -- it does not override anything in the root.

## Project

Composite GitHub Action that finds a user's pull requests to other people's repositories through the GitHub GraphQL search API and renders three self-hosted animated SVG cards into the caller's repo: a summary (counts, combined stars, a chip per project), the merged list, and the in-review list grouped by repository.

Built 2026-09-25 to publish as `Sagargupta16/oss-contributions-card-action@v1`. The card designs come from `brand/Sagargupta16/scripts/render-svgs.py` (`render_oss`, `render_list_card`, `render_oss_merged`, `render_oss_review`), which still renders the profile README's own copies from the curated portfolio list.

## Stack

- **Language**: Python, stdlib only. `action.yml` installs 3.13; CI tests 3.12, 3.13, 3.14 and 3.15
- **Framework**: GitHub Actions composite action (`action.yml`)
- **Database**: none
- **Package manager**: none (nothing to install); `uv`/`uvx` for local lint and tests
- **Deploy target**: consumed via `uses:` in other repos' workflows; releases are git tags

## Run

```
GITHUB_TOKEN=$(gh auth token) OSS_USERNAME=<login> OSS_EXCLUDE_OWNERS=<owner,...> OSS_EXCLUDE_REPOS=<owner/repo,owner/*,...> python oss_contributions_card.py
```

Writes `assets/oss.svg`, `assets/oss-merged.svg` and `assets/oss-review.svg` under the working directory unless `OSS_OUTPUT_*` point elsewhere. Pass the token inline like this; never echo it.

Regenerate the README previews from live data (Sagargupta16, minus MCA-NITW and the five one-line list repositories that the CI `action` job also excludes):

```
GITHUB_TOKEN=$(gh auth token) OSS_USERNAME=Sagargupta16 OSS_EXCLUDE_OWNERS=MCA-NITW OSS_EXCLUDE_REPOS=firstcontributions/first-contributions,emmabostian/developer-portfolios,is-a-dev/register,ossamamehmood/Hacktoberfest,SimplifyJobs/Summer2027-Internships OSS_OUTPUT_SUMMARY=examples/oss.svg OSS_OUTPUT_MERGED=examples/oss-merged.svg OSS_OUTPUT_REVIEW=examples/oss-review.svg python oss_contributions_card.py
```

## Test

```
uvx ruff@0.17.1 check .
uv run --no-project --with pytest==9.1.1 pytest -v
```

`test_oss_contributions_card.py` never touches the network: every test monkeypatches `fetch` (or calls the pure functions directly). It covers the query string, cursor pagination, the page cap, duplicate results, GraphQL errors, the https allowlist, owner, repository (exact, `owner/*`, case, empty input) and private-repo exclusion, star ranking, the `+N more` chip, grouping, max-rows, empty cards, SVG validity, escaping, dash and emoji normalization, config validation, `$GITHUB_OUTPUT`, and the keep-existing-cards fallback for five failure shapes.

`.github/workflows/ci.yml` runs three jobs on every push to `main` and every PR: `lint` (ruff), `test` (pytest on 3.12/3.13/3.14/3.15) and `action`, the only job that loads `action.yml`. It runs `uses: ./` as Sagargupta16 with the workflow token, `exclude-owners: MCA-NITW` and the job-level `EXCLUDE_REPOS` list as `exclude-repos`, then asserts all four outputs are numbers, all three SVGs parse, and no excluded repository appears on a card. `ruff==0.17.1` and `pytest==9.1.1` are pinned inline, because Renovate does not read `run:` blocks; bump them by hand, the same way as in `credly-badge-readme-action`. There is no `ruff.toml` on purpose: the tree passes ruff's full default ruleset.

## Entry points

- `action.yml` -- the contract: inputs, outputs, Python 3.13, inputs mapped to env vars, runs the script
- `oss_contributions_card.py` -- all of the logic: config, GraphQL search, filtering, rendering, writing files and `$GITHUB_OUTPUT`

## Key files

- `oss_contributions_card.py` -- `load_config` (inputs), `search_prs` (pagination), `select_upstream` (exclusion), `render_summary` / `render_merged` / `render_review` (cards), `main` (fallback and outputs)
- `examples/*.svg` -- README previews, generated from live data by the command under Run; never edit them by hand

## Gotchas

- Adding an input means touching three places in sync: `action.yml` inputs, the `action.yml` env block, and `load_config`.
- The username env var is `OSS_USERNAME`, never `USERNAME`: Windows already sets `USERNAME` to the local account name.
- Composite outputs need a `value:` mapping to `steps.render.outputs.<name>` and `id: render` on the step. Without them every output silently resolves to an empty string.
- The query is `is:pr author:USER is:STATE -user:USER`. `-user:` drops your own repositories on the server; `select_upstream` repeats that check case-insensitively and adds `exclude-owners`, `exclude-repos` (`owner/*` entries join the owner set) and private repositories. Exclusion happens before rendering, so it covers both lists, the summary counts and the outputs. The username is validated as a login because it is interpolated into the query.
- The search API stops at 1000 results, so `MAX_PAGES` is 10 and a warning prints when `issueCount` is higher.
- Any fetch failure keeps the existing cards: network and HTTP errors, a non-JSON body, GraphQL `errors` on an HTTP 200, and a missing `search` object. `FETCH_ERRORS` is that list; do not widen it to a bare `except`.
- A card is rewritten only when its content changed. Chips for repos under 1000 stars show exact counts, so the summary card still changes on most days.
- Titles pass through `plain()`: dash code points become `-`, and emoji and XML-invalid characters are dropped. The `CLEAN` table is built from integer code points so the source stays plain ASCII; a literal dash character anywhere in a file is blocked by the workspace dash hook.
- `_layout_chips` relies on every chip being under 500px wide (repo clipped to 60 characters), so `+N more` always fits after the first chip of a row. Raise the clip and that stops holding.
- Without chip overflow, `render_summary`, `render_merged` and `render_list_card` are byte-identical to the profile originals (checked 2026-09-25 by importing `render-svgs.py` and comparing). If the profile design changes, change both.
- No shebang on purpose: the action runs `python <script>`, and a shebang on a file committed from Windows as mode 100644 trips ruff `EXE001` on Linux CI.
- The CI `action` job hits the live API. A fresh checkout has no earlier cards, so a GitHub search outage turns that job red with exit 1.
- `v1` is a moving major tag: after cutting `v1.x.y`, move `v1` to it and update `CHANGELOG.md`.

## Repo-specific rules

- Keep the script stdlib-only. `action.yml` has no install step, so any third-party import breaks every consumer.
- Never print the token, and never put it anywhere but the `Authorization` header of a request to an `ALLOWED_HOSTS` URL.

## Usage

- In a workflow: `uses: Sagargupta16/oss-contributions-card-action@v1`, optionally with `exclude-owners` and `exclude-repos`. The consumer workflow commits the SVGs itself (see the README Quick start).
- Standalone: see Run.

## Config

- No config file. Everything flows action input -> env var -> script: `OSS_USERNAME`, `GITHUB_TOKEN` (or `GH_TOKEN` by hand), `OSS_EXCLUDE_OWNERS`, `OSS_EXCLUDE_REPOS`, `OSS_OUTPUT_SUMMARY`, `OSS_OUTPUT_MERGED`, `OSS_OUTPUT_REVIEW`, `OSS_MAX_ROWS`, `OSS_ACCENT`. The runner provides `GITHUB_OUTPUT`.
