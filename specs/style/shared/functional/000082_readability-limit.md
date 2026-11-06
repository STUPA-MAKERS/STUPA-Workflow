---
id: "000082"
title: Readability limits the single expression
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

# Readability limits the single expression

Split an expression that is deeper than three levels or longer than about eight lines into
named locals or a named helper function.

Reason: The goal is code that is easier to read.
