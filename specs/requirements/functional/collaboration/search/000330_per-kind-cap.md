---
id: "000330"
title: Search shows 5 hits per kind
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/search
  - frontend/src/app/layout
scope:
  - backend/app/modules/search
  - frontend/src/app/layout
---

# Search shows 5 hits per kind

Each source must return at most 5 hits. If there are more, the palette must say that the list
is not complete.
