#!/usr/bin/env bash
# Commit state/ changes back to the repo (retries if another run pushed first).
set -euo pipefail
git config user.name "ai-stories-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add state
if git diff --cached --quiet; then echo "no state changes"; exit 0; fi
git commit -q -m "state: $1 $(date -u +%Y-%m-%dT%H:%MZ)"
for i in 1 2 3 4 5; do
  if git push -q; then echo "state saved"; exit 0; fi
  git pull -q --rebase -X theirs || true
  sleep $((i * 3))
done
echo "could not push state"; exit 1
