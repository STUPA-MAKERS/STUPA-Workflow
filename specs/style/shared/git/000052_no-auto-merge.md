---
id: "000052"
title: A pull request is never set to auto-merge
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - .
---

# A pull request is never set to auto-merge

Do not use `gh pr merge --auto`.

Reason: The branches have no protection, so `--auto` merges at once.
