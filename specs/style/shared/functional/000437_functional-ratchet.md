---
id: "000437"
title: A CI ratchet keeps the functional style from getting worse
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/
  - frontend/
  - ui-kit
  - mcp/
  - typst/
  - .github/workflows
---

# A CI ratchet keeps the functional style from getting worse

A script counts the violations of the functional style rules against a stored baseline. CI
fails when the count goes up. A change that lowers the count also lowers the baseline.
