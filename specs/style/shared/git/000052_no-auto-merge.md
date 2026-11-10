---
id: "000052"
title: A pull request is never set to auto-merge
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - .
scope:
  - .
---

# A pull request is never set to auto-merge

An agent must not use `gh pr merge --auto`.

Reason: `--auto` merges when the checks are green, without the go of the owner (000054).
