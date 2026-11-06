---
id: "000085"
title: Comprehensions instead of loops
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - backend/app/
  - backend/worker/
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - mcp/
  - typst/typst_service/
---

# Comprehensions instead of loops

A loop that builds a value must be a comprehension, a generator expression or
`map`/`filter`/`flatMap`/`reduce`. Do not use `forEach`. A loop that only causes effects stays
a `for` statement.

Reason: A comprehension whose result nobody reads hides the effect.
