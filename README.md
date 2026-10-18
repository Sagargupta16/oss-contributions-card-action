# OSS Contributions Card

[![CI](https://github.com/Sagargupta16/oss-contributions-card-action/actions/workflows/ci.yml/badge.svg)](https://github.com/Sagargupta16/oss-contributions-card-action/actions/workflows/ci.yml)
[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-OSS%20Contributions%20Card-blue?logo=github)](https://github.com/marketplace/actions/oss-contributions-card)
[![Release](https://img.shields.io/github/v/release/Sagargupta16/oss-contributions-card-action)](https://github.com/Sagargupta16/oss-contributions-card-action/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A GitHub Action that finds your pull requests to other people's repositories and renders them as animated SVG cards in your own repo. There is no list to maintain: every run searches GitHub, so a pull request shows up when you open it and moves to the merged card when it lands.

It writes three cards, each in an 840px desktop layout and a 320px phone layout:

- **Summary**: merged upstream, in review, projects contributed to, the combined stars of those projects, and a chip per project ranked by stars.
- **Merged**: repository, title and number of every merged pull request, newest first.
- **In review**: open pull requests, grouped by repository.

The cards are committed to your repo (the action can do the commit for you), so there is no widget host to run out of quota or go down. Each SVG is self-contained (CSS and SMIL animation only, no scripts, fonts or external images), which is what GitHub needs to render it through an `<img>`.

It is published on the [GitHub Marketplace](https://github.com/marketplace/actions/oss-contributions-card).

## Why an action and not a stats widget

| | Hosted stats widgets | This action |
| --- | --- | --- |
| What it shows | Your own repositories, commits, streaks | Pull requests you landed in other people's projects |
| Where the image lives | A shared server renders it on every view | Committed to your repo by your own scheduled workflow |
| Rate limits and outages | Shared quota; the card breaks when the host is down | Your own workflow token; a failed run keeps yesterday's cards |
| Runtime dependencies | The host's stack | Python standard library only |

## Preview

Live output for [@Sagargupta16](https://github.com/Sagargupta16), rendered on 2026-10-18 with `exclude-owners: MCA-NITW` and five one-line list repositories in `exclude-repos`:

<picture><source media="(max-width: 600px)" srcset="examples/oss-mobile.svg" /><img src="examples/oss.svg" width="100%" alt="Open source summary: merged upstream, in review, projects and combined stars" /></picture>

<picture><source media="(max-width: 600px)" srcset="examples/oss-merged-mobile.svg" /><img src="examples/oss-merged.svg" width="100%" alt="Merged upstream pull requests, newest first" /></picture>

<picture><source media="(max-width: 600px)" srcset="examples/oss-review-mobile.svg" /><img src="examples/oss-review.svg" width="100%" alt="Pull requests in review, grouped by repository" /></picture>

### Phone layout

An 840px card scaled down to a phone screen shrinks its text to a few pixels. The phone layouts are 320px wide, so they render close to their real size: the tiles go two by two, titles wrap instead of being clipped, and the lists show the newest six merged pull requests and the top five repositories in review. Open this page on a phone and the previews above switch to them; on a desktop, here are two of them side by side:

<img src="examples/oss-mobile.svg" width="300" alt="Phone layout of the summary card" /> <img src="examples/oss-merged-mobile.svg" width="300" alt="Phone layout of the merged card" />

## Quick start

Create `.github/workflows/oss-cards.yml` in the repo that shows the cards, usually your profile README repo:

```yaml
name: OSS contribution cards

on:
  schedule:
    - cron: "30 6 * * *" # daily
  workflow_dispatch:

permissions:
  contents: write

jobs:
  cards:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - uses: Sagargupta16/oss-contributions-card-action@v1
        with:
          commit: true
          exclude-owners: "your-org" # optional: owners whose repositories should not count
```

`username` defaults to the owner of the repo the workflow runs in and `token` to the workflow's own token, so in your own profile repo nothing else is required. With `commit: true` the action commits the six cards as `github-actions[bot]` and pushes them to the checked-out branch, only when a card changed. Only the card files go into that commit. If the branch moved during the run, it rebases and pushes once more. On a `pull_request` run the checkout is a detached merge commit, so it prints a warning and commits nothing.

### Commit the cards yourself

Leave `commit` off and add your own step when you want a different identity, a signed commit or a pull request instead of a push:

```yaml
      - uses: Sagargupta16/oss-contributions-card-action@v1

      - name: Commit the cards if they changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add assets/oss*.svg
          if ! git diff --cached --quiet; then
            git commit -m "chore: refresh oss contribution cards"
            git push
          fi
```

### Leave out list repositories

Adding your name to a list, like first-contributions or a portfolio collection, is a real merged pull request, so the search counts it. To keep those off the cards, list them in `exclude-repos`:

```yaml
      - uses: Sagargupta16/oss-contributions-card-action@v1
        with:
          exclude-owners: "your-org"
          exclude-repos: "firstcontributions/first-contributions, emmabostian/developer-portfolios, is-a-dev/*"
```

`owner/repo` drops one repository and `owner/*` drops every repository of that owner. Matching is case-insensitive, and it applies to the merged card, the in-review card, the summary counts and the action outputs alike.

To drop small repositories in general instead of naming each one, set `min-stars`. Every repository with fewer stars than that is left out the same way:

```yaml
      - uses: Sagargupta16/oss-contributions-card-action@v1
        with:
          min-stars: 50
```

## Embed

Point the images at the cards and wrap each one in a link to the matching GitHub search, so a click shows the pull requests behind it. Each `<picture>` gives phones (600px and narrower) the 320px layout and everything else the 840px one. Replace `YOUR-LOGIN` with your GitHub login:

```html
<a href="https://github.com/search?q=is%3Apr+author%3AYOUR-LOGIN+is%3Amerged+-user%3AYOUR-LOGIN&type=pullrequests">
  <picture>
    <source media="(max-width: 600px)" srcset="assets/oss-mobile.svg" />
    <img src="assets/oss.svg" width="100%" alt="Open source summary" />
  </picture>
</a>
<a href="https://github.com/search?q=is%3Apr+author%3AYOUR-LOGIN+is%3Amerged+-user%3AYOUR-LOGIN&type=pullrequests">
  <picture>
    <source media="(max-width: 600px)" srcset="assets/oss-merged-mobile.svg" />
    <img src="assets/oss-merged.svg" width="100%" alt="Merged upstream pull requests" />
  </picture>
</a>
<a href="https://github.com/search?q=is%3Apr+author%3AYOUR-LOGIN+is%3Aopen+-user%3AYOUR-LOGIN&type=pullrequests">
  <picture>
    <source media="(max-width: 600px)" srcset="assets/oss-review-mobile.svg" />
    <img src="assets/oss-review.svg" width="100%" alt="Pull requests in review" />
  </picture>
</a>
```

If you exclude anything, add the same exclusions to each link so the search lists the same pull requests as the card: `+-user%3AOWNER` for every excluded owner (and every `owner/*` entry), and `+-repo%3AOWNER%2FREPO` for every excluded repository.

## Inputs

| Input | Default | Description |
| --- | --- | --- |
| `username` | `${{ github.repository_owner }}` | GitHub login whose pull requests are counted |
| `token` | `${{ github.token }}` | Token for the GitHub GraphQL API. The workflow's own token can read public pull requests |
| `exclude-owners` | `""` | Comma-separated owners whose repositories do not count, for example your own organizations |
| `exclude-repos` | `""` | Comma-separated repositories that do not count, as `owner/repo`, or `owner/*` for every repository of an owner. Case-insensitive |
| `output-summary` | `assets/oss.svg` | Path of the summary card. An empty string skips it |
| `output-merged` | `assets/oss-merged.svg` | Path of the merged card. An empty string skips it |
| `output-review` | `assets/oss-review.svg` | Path of the in-review card. An empty string skips it |
| `output-summary-mobile` | `assets/oss-mobile.svg` | Path of the 320px phone layout of the summary card. An empty string skips it |
| `output-merged-mobile` | `assets/oss-merged-mobile.svg` | Path of the phone layout of the merged card. An empty string skips it |
| `output-review-mobile` | `assets/oss-review-mobile.svg` | Path of the phone layout of the in-review card. An empty string skips it |
| `max-rows` | `12` | Most rows on each list card. The rest are summed in a footer line |
| `accent` | `""` | Hex color for the summary card's heading and project chips, for example `#a78bfa`. Empty keeps the stock blue. The merged and in-review cards stay green and amber so status reads at a glance |
| `min-stars` | `0` | Leave out repositories with fewer stars than this. `0` keeps every repository |
| `commit` | `false` | `true` commits the changed cards as `github-actions[bot]` and pushes them to the checked-out branch. Needs `permissions: contents: write` |
| `commit-message` | `chore: refresh oss contribution cards` | Commit message used when `commit` is `true` |

## Outputs

| Output | Description |
| --- | --- |
| `merged` | Merged pull requests counted |
| `open` | Open pull requests counted |
| `projects` | Repositories with at least one merged pull request |
| `stars` | Combined stars of those repositories |

When the GitHub API fails and the action keeps your existing cards, it sets no outputs, so all four are empty strings.

## Run summary

Every run also writes a Markdown report to its own page under Actions: the four counts, how many pull requests were left out (your own repositories, private repositories, `exclude-owners`, `exclude-repos` and `min-stars`), and a table of every merged and in-review pull request with its repository, stars and link. Check it after changing an exclusion to see what the cards count without opening the SVGs.

## How it works

```mermaid
flowchart LR
    cron["Your workflow<br/>(schedule or manual)"] --> action["oss_contributions_card.py<br/>(composite action, Python stdlib)"]
    action -- "search: is:pr is:merged / is:open<br/>100 per page, up to 1000" --> gql[("GitHub GraphQL API")]
    gql --> filter["Drop own repos, private repos,<br/>exclude-owners, exclude-repos, min-stars"]
    filter --> render["Render summary, merged and in-review<br/>SVGs, desktop and phone layouts"]
    filter --> report["Markdown table in<br/>the run summary"]
    render --> write["Write a card only if it changed"]
    write --> commit["commit: true pushes as github-actions[bot],<br/>or your own step commits assets/oss*.svg"]
    gql -. "API error" .-> keep["Keep existing cards,<br/>warn, exit 0"]
```

1. Runs two GitHub GraphQL searches, `is:pr author:USER is:merged -user:USER` and the same with `is:open`, following the cursor 100 results at a time.
2. Drops pull requests to repositories you own, to anything matched by `exclude-owners` or `exclude-repos` (case-insensitive), to repositories under `min-stars`, and to private repositories, even when the token can see them.
3. Renders the three cards in both layouts. Projects are ranked by stars; merged pull requests are ordered by merge date; open ones are grouped by repository, the repository with the most open pull requests first.
4. Writes each card only when its content changed, so a quiet day produces no commit, and writes the run summary.
5. With `commit: true`, commits the changed cards and pushes them.

If the GitHub API fails (network error, HTTP error, rate limit, a GraphQL error), the action keeps the cards already in your repo, prints a warning and exits 0, so a flaky API never blanks your README. If a card does not exist yet, there is nothing to keep, and it exits 1 with a message naming the missing file.

Pull request titles are untrusted text: they are HTML-escaped before they go into an SVG, en and em dashes become plain hyphens, and emoji are dropped. The token is only sent to `https://api.github.com` and is never printed. The script is Python standard library only, so there is no dependency tree to audit.

## Limits

- **Public pull requests only.** Private repositories are always dropped, so nothing private reaches a public README.
- **1000 results per search.** GitHub's search API stops at 1000 results per query. Past that the counts are capped, and the run prints a warning with the real total.
- **Everything the search finds counts** unless you exclude it. That includes one-line additions to lists such as first-contributions, awesome lists or portfolio collections: see [Leave out list repositories](#leave-out-list-repositories).
- **Stars are today's stars**, not the count when your pull request merged.
- **The summary card shows four rows of project chips**, and its phone layout the top 12 projects. When there are more projects than fit, the last chip reads `+N more`. The tile above still counts every project.
- **The search link cannot filter by stars.** GitHub search has no stars qualifier for pull requests, so with `min-stars` set, the linked search lists more than the card.
- **Only pull requests you opened.** Reviews, issues and commits co-authored on someone else's pull request are not counted, and pull requests closed without merging are not shown.

## License

[MIT](LICENSE)
