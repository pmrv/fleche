#!/usr/bin/env bash
# Regenerate the git-derived inputs for analyze.py / render_html.py.
#
#   merged.txt    PR numbers squash-merged into main, newest first
#   diffstat.csv  <pr>,<insertions>,<deletions>,<files> for each of those merges
#
# prs.csv and closed-unmerged.txt come from the GitHub API instead and are
# checked in; see README.md for the queries that produced them.
set -euo pipefail
cd "$(dirname "$0")"
ROOT=$(git rev-parse --show-toplevel)

git -C "$ROOT" log --format='%s' main \
  | grep -oE '\(#[0-9]+\)$' | tr -d '(#)' > merged.txt

git -C "$ROOT" log --format='%H %s' main | grep -E '\(#[0-9]+\)$' \
| while read -r sha rest; do
    n=$(printf '%s' "$rest" | grep -oE '\(#[0-9]+\)$' | tr -d '(#)')
    printf '%s,%s\n' "$n" \
      "$(git -C "$ROOT" show --numstat --format='' "$sha" \
         | awk '{a+=$1; d+=$2; f++} END{printf "%d,%d,%d", a+0, d+0, f+0}')"
  done > diffstat.csv

wc -l < merged.txt | xargs printf 'merged.txt: %s PRs\n'
