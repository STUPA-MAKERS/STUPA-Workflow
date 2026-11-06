---
id: "000086"
title: A branch on one value is an exhaustive match
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/
  - backend/worker/
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - mcp/
  - typst/typst_service/
---

# A branch on one value is an exhaustive match

A branch on one value with two or more outcomes must be a `match` in Python or a `switch` in
TypeScript. Every case must have a `return`. The match must be exhaustive: `assert_never` in
Python, `assertNever` in TypeScript. A binary choice must be a conditional expression, nested
at most one level.
