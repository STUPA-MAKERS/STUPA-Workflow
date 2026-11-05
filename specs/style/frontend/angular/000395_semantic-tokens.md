---
id: "000395"
title: Components use semantic colour tokens
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - frontend/src/app/
  - ui-kit
---

# Components use semantic colour tokens

A component uses only semantic tokens (`--color-*`), never primitives (`--c-*`). A new colour
starts as a primitive and gets a mapping per theme.
