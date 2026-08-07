# Project statistics

A snapshot of how `fleche` has been built, from the first pull request to
2026-08-07. Numbers are counts, not judgements — this is the shape of the
work, not a scorecard.

Regenerate with:

```console
$ ./collect.sh          # derives merged.txt + diffstat.csv from git
$ python3 analyze.py    # the report below
$ python3 render_html.py # same data as a standalone stats.html page
```

## Inputs

| File | Source |
|---|---|
| `prs.csv` | GitHub search API — `repo:pmrv/fleche is:pr`, one row per PR: `number,created_at,closed_at,conversation_comments` (dates are `MM-DDTHH:MM:SS`, all 2026, empty `closed_at` = still open) |
| `closed-unmerged.txt` | GitHub search API — `repo:pmrv/fleche is:pr is:closed is:unmerged` |
| `merged.txt`, `diffstat.csv` | derived from `git log main` by `collect.sh` |

A PR counts as **merged** if it closed and is not in `closed-unmerged.txt`.
That deliberately includes PRs merged into a *parent PR branch* rather than
into `main` — the stacked-PR workflow means a good number never touch `main`
directly.

Two caveats worth knowing before quoting these:

- **Conversation comments only.** The `comments` field counts top-level PR
  discussion. Inline review-thread comments need one API call per PR and are
  not in this dataset.
- **Pre-squash commit counts are not recoverable.** The squash-merge messages
  in this repo don't carry the original commit list, so "commits per PR" can't
  be reconstructed. `main` itself carries 648 commits, 479 of which are PR
  squashes.

## Report

```
PROJECT WINDOW  2026-02-09 -> 2026-08-07   (180 days, 25.7 weeks)
PRs opened      617
PRs merged      572  (93%)
  ├─ squash-merged into main    478
  └─ merged into another PR branch (stacked)  94
PRs closed unmerged 39   still open 6
Merge rate      3.18/day   22.2/week
Lines merged    +44,586 / -16,766  across 1,349 file-touches
Comments        916 conversation comments on PRs

── PRs merged per week ───────────────────────────────────────
  Feb 09 │████████████████                             19
  Feb 16 │█████████████████                            20
  Feb 23 │████████████████████                         24
  Mar 02 │██████████████████████████                   31
  Mar 09 │███████                                      9
  Mar 16 │██████████████████                           22
  Mar 23 │███████████████                              18
  Mar 30 │██████████████████████████████               36
  Apr 06 │████████████████                             19
  Apr 13 │██████████████████                           22
  Apr 20 │████████████████████████████████████████████ 53
  Apr 27 │███████████████████████                      28
  May 04 │██████████████████████████                   31
  May 11 │██████████                                   12
  May 18 │█████████████████                            21
  May 25 │██████████████████████████████               36
  Jun 01 │████████████████████                         24
  Jun 08 │████████                                     10
  Jun 15 │███████████████                              18
  Jun 22 │██████████                                   12
  Jun 29 │████████████████                             19
  Jul 06 │█████████████████                            21
  Jul 13 │███████████████                              18
  Jul 20 │████████████████████                         24
  Jul 27 │██████████                                   12
  Aug 03 │███████████                                  13

── PRs opened per month ──────────────────────────────────────
  2026-02 │███████████████████████                      71
  2026-03 │██████████████████████████████████████       117
  2026-04 │████████████████████████████████████████████ 134
  2026-05 │█████████████████████████████████████        113
  2026-06 │█████████████████████████                    77
  2026-07 │█████████████████████████████                87
  2026-08 │██████                                       18

── PR open duration (merged PRs) ─────────────────────────────
    < 1 h │████████████████████████████████████████████ 286
    1–4 h │███████                                      44
   4–12 h │████████                                     54
  12–24 h │█████████████                                85
    1–2 d │███████                                      45
    2–7 d │███████                                      48
    > 7 d │██                                           10

  median 1.0 h   p25 0.1 h   p75 16.0 h   p90 49.9 h   max 19.2 d
  82% of merged PRs landed within 24 h

── Conversation comments per PR ──────────────────────────────
      0 │████████████████████████████████████████████ 330
      1 │████████████████████                         148
      2 │██████                                       43
    3–4 │█████                                        40
    5–8 │████                                         32
   9–14 │██                                           15
  15–24 │█                                            8
    25+ │                                             1

  total 916   mean 1.5   median 0   busiest PR #107 with 55 comments
  47% of PRs drew at least one comment

── PR size — lines changed (merged) ──────────────────────────
      < 10 │███████████████████████████████████████      129
     10–49 │███████████████████████████████████████      130
    50–199 │████████████████████████████████████████████ 145
   200–499 │██████████████                               47
  500–1499 │████████                                     25
     1500+ │█                                            3

  median 39 lines   mean 128   largest 3,060

── PRs opened by weekday ─────────────────────────────────────
  Mon │████████████████████████████████████████████ 163
  Tue │████████████████████                         75
  Wed │█████████████████████████████                108
  Thu │███████████████████                          72
  Fri │████████████████████████████                 104
  Sat │█████████                                    34
  Sun │████████████████                             61

── PRs opened by hour (UTC) ──────────────────────────────────
  00–02 │███████████                                  45
  03–05 │████████████████████████████████████████████ 181
  06–08 │███████                                      27
  09–11 │████                                         16
  12–14 │██████████████                               58
  15–17 │█████████████████████████                    104
  18–20 │█████████████████████████                    104
  21–23 │████████████████████                         82

```

## Commit subjects on `main`

479 of the 648 commits on `main` are PR squashes; the other 169 are the
pre-PR-workflow commits from the first week of February 2026. Of the squashes,
294 use a conventional-commit prefix:

| type | count |
|---|---|
| docs | 139 |
| refactor | 33 |
| test | 30 |
| fix | 26 |
| feat | 25 |
| ci | 17 |
| chore | 9 |
| build | 9 |
| perf | 5 |
| bench | 1 |
| *(free-form subject)* | 185 |
