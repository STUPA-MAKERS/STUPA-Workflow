---
id: "000408"
title: Fixed bottom elements sit above the bottom bar
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/
  - frontend/vendor/ui-kit
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Fixed bottom elements sit above the bottom bar

A fixed or sticky element at the bottom of a page must use `var(--app-bottom-inset)`. A page
with a FAB must reserve space, so the FAB never covers the end of the page.
