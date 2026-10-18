# Contributing to oss-contributions-card-action

This repo is a composite GitHub Action that finds your pull requests to other people's repositories and renders three self-hosted, animated SVG cards: a summary, the merged list and the in-review list. Bug reports, fixes, doc corrections and new inputs that come with tests are welcome.

## Setup

The script is Python standard library only and `action.yml` has no install step, so there is nothing to install. Lint and tests run with `uv`/`uvx` locally; CI uses pip with pinned versions.

## Before you open a PR

CI (`.github/workflows/ci.yml`) runs three jobs on every push to `main` and every pull request:

- `lint`: `pip install --only-binary :all: ruff==0.17.1`, then `ruff check .` on Python 3.13
- `test`: `pip install --only-binary :all: pytest==9.1.1`, then `pytest -v` on Python 3.12, 3.13, 3.14 and 3.15
- `action`: runs `action.yml` from the checkout against the live search API with `exclude-owners` and `exclude-repos` set, then asserts all four outputs are numbers, all three SVGs parse, and no excluded repository appears on a card

Run the first two locally:

```bash
uvx ruff@0.17.1 check .
uv run --no-project --with pytest==9.1.1 pytest -v
```

The `action` job hits the live GitHub search API, so a search outage can turn it red on its own.

To render the cards by hand, pass a token inline and never echo it:

```bash
GITHUB_TOKEN=$(gh auth token) OSS_USERNAME=<login> python oss_contributions_card.py
```

That writes `assets/oss.svg`, `assets/oss-merged.svg` and `assets/oss-review.svg` unless `OSS_OUTPUT_SUMMARY`, `OSS_OUTPUT_MERGED` and `OSS_OUTPUT_REVIEW` point elsewhere. Do not commit them. The previews in `examples/` are generated from live data; never edit them by hand.

## Conventions

- Tests live in `test_oss_contributions_card.py` at the repo root and never touch the network: every test monkeypatches `fetch` or calls the pure functions directly.
- A new input touches three places in sync: `inputs` in `action.yml`, the `env` block in `action.yml`, and `load_config` in the script.
- The username env var is `OSS_USERNAME`, never `USERNAME`, because Windows already sets `USERNAME`.
- Composite outputs need a `value:` mapping to `steps.render.outputs.<name>` and `id: render` on the step.
- Keep the script standard library only. Any third-party import breaks every consumer.
- Never print the token, and send it only in the `Authorization` header of a request to an `ALLOWED_HOSTS` URL.
- `FETCH_ERRORS` lists the failures that keep the existing cards. Do not widen it to a bare `except`.
- Pull request titles are untrusted: they pass through `plain()` and `html.escape` before reaching an SVG. Keep the source plain ASCII; the dash table is built from integer code points for that reason.
- There is no `ruff.toml` and no shebang on purpose. The `ruff` and `pytest` pins in `ci.yml` are bumped by hand, because Renovate does not read `run:` blocks.
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`).
- Add a `CHANGELOG.md` entry under a concrete next version, for example `## [1.0.1] - YYYY-MM-DD`, grouped under `Added`, `Changed` or `Fixed`.

## Security issues

Do not report vulnerabilities in public issues. Follow [SECURITY.md](SECURITY.md).

## License

This project is released under the MIT License (see [LICENSE](LICENSE)). By contributing, you agree that your contributions are licensed under it.
