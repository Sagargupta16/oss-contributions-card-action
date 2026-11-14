# Changelog

## [1.2.0] - 2026-11-14

### Added

- `style` input: `classic` (the default) or `flat`. `flat` draws the newer look of the profile README these cards come from, ported from its design kit and open-source cards into `flat_style.py`: flat cards with one fill and one hairline border, mono micro-labels (10.5px on desktop, 11.5px on a phone), one blue family, green only on the newest merge and amber only on work in review, no gradient or shine. Every loop lasts 2, 3, 4, 6, 12 or 24 s, and every entrance is poster-safe, so a still render shows the whole card.
- With `style: flat` the summary card (`output-summary`, `output-summary-mobile`) shows four tiles (merged upstream, repositories with merges, combined stars, open pull requests), FIRST MERGE and UPDATED labels, and a ledger of the six newest merges with their number, title, date and stars, the newest marked green. Five rows are in view and the ledger steps up a row every 4 s. ALSO MERGED INTO names up to three repositories the ledger does not show, and a "+N more pull requests on GitHub" line counts the rest. The in-review card (`output-review`, `output-review-mobile`) shows a chip per repository with its open pull request count and stars, the most starred first. The phone layouts are 320px wide with the same tiles, rail and chips.
- `max-rows` caps the flat ledger (six at most) and the repositories on the flat in-review cards.
- Flat previews in `examples/` (`oss-flat.svg`, `oss-review-flat.svg` and their `-mobile` layouts), rendered from live data on 2026-11-14.
- Tests for the flat cards (poster-safe entrances, loops on the clock, the text size floor, no gradient or shine, 320px phone width, text inside the phone card), and a test that the default style still writes the same bytes as 1.1.0.
- CI's `action` job also runs the action with `style: flat` and checks its four cards.

### Changed

- Nothing for existing workflows: without `style`, or with `style: classic`, every card is byte-identical to 1.1.0. `flat` writes no merged card, since its summary carries the merged list, and leaves `accent` unused. The flat summary shows the run's date, so it changes on every run.

## [1.1.0] - 2026-10-18

### Added

- Phone layouts. Every card is now also rendered 320px wide (`assets/oss-mobile.svg`, `assets/oss-merged-mobile.svg`, `assets/oss-review-mobile.svg`), ported from the profile README's `mobile_cards.py`: tiles two by two, wrapped titles instead of clipped ones, the newest six merged pull requests, the top five repositories in review and the top 12 project chips, with the same entrance, pulse and shine motion. New inputs `output-summary-mobile`, `output-merged-mobile` and `output-review-mobile`; an empty string skips a card. The README embed snippet uses `<picture>` to pick them below 600px.
- `commit` and `commit-message` inputs. With `commit: true` the action commits only the changed cards as `github-actions[bot]` and pushes them to the checked-out branch, rebasing and retrying once if the branch moved. A detached HEAD (a `pull_request` run) prints a warning and commits nothing. The Quick start is now one step.
- `min-stars` input: repositories with fewer stars are left out of every card, the counts and the outputs.
- A run summary: each run writes the counts, how many pull requests were left out, and a Markdown table of every merged and in-review pull request to `$GITHUB_STEP_SUMMARY`.

### Fixed

- Project chips for repositories with a million or more stars read `1.2M` instead of `1200.0K`.

### Changed

- CI's `action` job checks that all six cards parse and keep excluded repositories off.
- README previews switch to the phone layouts on narrow screens, regenerated from live data on 2026-10-18.

## [1.0.1] - 2026-10-18

### Changed

- `action.yml` runs the script through `$GITHUB_ACTION_PATH` instead of interpolating `${{ github.action_path }}` into the shell line, as GitHub's security hardening guide recommends.
- CI lints with ruff 0.17.1 (was 0.16.6) and tests on Python 3.15 as well as 3.12, 3.13 and 3.14.
- CI checkouts set `persist-credentials: false`, since no job pushes.
- README: CI, Marketplace, release and license badges, a Marketplace link, a comparison with hosted stats widgets, and a flow diagram under How it works.
- README previews regenerated from live data on 2026-10-18.
- `CONTRIBUTING.md` and `CLAUDE.md` list the new ruff pin and Python matrix.

## [1.0.0] - 2026-09-25

Initial release.

### Added

- Composite action that finds your pull requests to other people's repositories with the GitHub GraphQL search API, following the cursor 100 results at a time, and renders three self-contained animated SVG cards: a summary, the merged pull requests newest first, and the open ones grouped by repository.
- Repositories you own and private repositories are always left out. `exclude-owners` leaves out whole owners, such as your own organizations, and `exclude-repos` leaves out single repositories (`owner/repo`) or every repository of an owner (`owner/*`), case-insensitively, from both lists, the summary counts and the outputs.
- Inputs `username`, `token`, `exclude-owners`, `exclude-repos`, `output-summary`, `output-merged`, `output-review` (an empty string skips that card), `max-rows` and `accent`.
- Outputs `merged`, `open`, `projects` and `stars`.
- When the GitHub API fails, the existing cards are kept and the run exits 0. With no earlier card to keep, it exits 1.
- Pull request titles are HTML-escaped, en and em dashes become hyphens, and emoji are dropped.
- Installs Python 3.13 with `actions/setup-python@v7`.
- CI: ruff, pytest on Python 3.12, 3.13 and 3.14, and a job that runs `action.yml` from the checkout against the live API and checks that `exclude-repos` keeps the listed repositories off every card.
