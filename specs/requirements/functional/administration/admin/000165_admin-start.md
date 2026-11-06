---
id: "000165"
title: Verwaltung keeps its frame widths
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/pages/admin/admin-frame/admin-frame.component.scss
  - frontend/src/app/pages/admin/admin-frame/frame-modes.ts
scope:
  - frontend/src/app/pages/admin
---

# Verwaltung keeps its frame widths

The frame widths must not change between `/admin` and `/admin/*`.
