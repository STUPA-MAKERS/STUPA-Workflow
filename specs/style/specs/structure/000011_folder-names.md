---
id: "000011"
title: Folder names are lower case kebab case
kind: style
status: draft
scope:
  - specs/
owner: frederikbeimgraben
updated: 2026-11-05
---

# Folder names are lower case kebab case

Folder names use only `a` to `z`, `0` to `9` and `-`.

Reason: The folder names become part of the rule IDs, where `/` is the separator.

Test: Every folder name below `specs/` matches `^[a-z0-9]+(-[a-z0-9]+)*$`.
