---
id: "000211"
title: A swipe never deletes
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/vendor/ui-kit/src/lib/row-swipe
  - frontend/vendor/ui-kit/src/lib/long-press
  - frontend/vendor/ui-kit/src/lib/selection-bar
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A swipe never deletes

A swipe on a list row must not delete. A long press starts the multi-select. The select bar
shows below the filters.
