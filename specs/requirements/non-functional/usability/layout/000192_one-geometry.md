---
id: "000192"
title: All list and detail pages share one geometry
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

# All list and detail pages share one geometry

Every page with a list and a detail pane must use the shared layout class, the shared left
column width and `app-page-header`. The document must not scroll. Each pane must scroll inside.
