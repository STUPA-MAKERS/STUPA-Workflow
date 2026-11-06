---
id: "000329"
title: Search needs two characters
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/search/service.py
  - backend/app/modules/search/router.py
  - frontend/src/app/features/search/search-palette.component.ts
scope:
  - backend/app/modules/search
  - frontend/src/app/layout
---

# Search needs two characters

A search with fewer than 2 characters must give an empty result, never an error. The query must
be at most 200 characters long.
