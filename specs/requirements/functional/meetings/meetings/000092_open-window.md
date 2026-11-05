---
id: "000092"
title: A meeting opens in a configured window
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - backend/app/modules/admin
---

# A meeting opens in a configured window

A meeting can be opened at the earliest `open_lead_minutes` before its planned start. Up to
`confirm_lead_minutes` before the start, the open needs an extra confirmation dialog. Both
values are admin settings.
