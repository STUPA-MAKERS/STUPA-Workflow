---
id: "000081"
title: A function body has one shape
kind: style
status: approved
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

# A function body has one shape

A function body is: guard raises, then single-assignment locals, then either one `return` of
an expression or one `match`/`switch` with one `return` per case. The goal is a body that is
only the `return`.
