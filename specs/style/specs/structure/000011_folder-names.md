---
id: "000011"
title: Folder names are lower case kebab case
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - specs/
scope:
  - specs/
---

# Folder names are lower case kebab case

Folder names must use only `a` to `z`, `0` to `9` and `-`.

Reason: The folder names become part of the rule IDs, where `/` is the separator.

Test: `scripts/check_specs.py`: every folder name below `specs/` matches
`^[a-z0-9]+(-[a-z0-9]+)*$`.
