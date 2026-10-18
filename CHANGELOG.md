# Changelog

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
