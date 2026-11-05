---
id: "000086"
title: A branch on one value is an exhaustive match
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
  - backend/worker/
  - frontend/src/app/
  - ui-kit
  - mcp/
  - typst/typst_service/
---

# A branch on one value is an exhaustive match

Write a branch on one value with two or more outcomes as a `match` in Python or a `switch`
in TypeScript. Every case has a `return`. The match is exhaustive: `assert_never` in Python,
`assertNever` in TypeScript. A binary choice is a conditional expression, nested at most one
level.
