---
id: "000083"
title: A local is bound once
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

# A local is bound once

A local name gets exactly one assignment. Do not rebind a name, do not use `+=`, a counter or a
flag that a branch sets. In TypeScript, use `const`, never `let`.
