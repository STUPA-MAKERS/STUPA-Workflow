---
id: "000408"
title: Fixed bottom elements sit above the bottom bar
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - frontend/src/app/
  - ui-kit
---

# Fixed bottom elements sit above the bottom bar

A fixed or sticky element at the bottom of a page uses `var(--app-bottom-inset)`. A page with
a FAB reserves space, so the FAB never covers the end of the page.
