---
id: "000092"
title: A meeting opens in a configured window
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote/open_window.py
  - frontend/src/app/features/meetings/open-window.util.ts
  - frontend/src/app/features/meetings/early-open-dialog
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - backend/app/modules/admin
---

# A meeting opens in a configured window

A meeting must open at the earliest `open_lead_minutes` before its planned start. Up to
`confirm_lead_minutes` before the start, the open must need an extra confirmation dialog. Both
values must be admin settings.
