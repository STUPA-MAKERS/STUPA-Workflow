---
id: "000395"
title: Components use semantic colour tokens
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/vendor/ui-kit/src/styles/tokens.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Components use semantic colour tokens

A component must use only semantic tokens (`--color-*`), never primitives (`--c-*`). A new
colour must start as a primitive and must get a mapping per theme.
