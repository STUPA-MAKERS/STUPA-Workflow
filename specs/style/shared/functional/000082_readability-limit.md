---
id: "000082"
title: Readability limits the single expression
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

# Readability limits the single expression

Code must split an expression that is deeper than three levels or longer than 8 lines. The
parts must become named locals or a named helper function.

Reason: The goal is code that is easier to read.
