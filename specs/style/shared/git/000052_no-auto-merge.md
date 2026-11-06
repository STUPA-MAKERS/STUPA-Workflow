---
id: "000052"
title: A pull request is never set to auto-merge
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - .
scope:
  - .
---

# A pull request is never set to auto-merge

An agent must not use `gh pr merge --auto`.

Reason: The branches have no protection, so `--auto` merges at once.
