---
id: "000083"
title: A local is bound once
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

# A local is bound once

A local name must get exactly one assignment. Code must not rebind a name or use `+=`, a
counter or a flag that a branch sets. TypeScript must use `const`, never `let`.
