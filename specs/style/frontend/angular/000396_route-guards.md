---
id: "000396"
title: A route guard is only for the UX
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/
scope:
  - frontend/src/app/
---

# A route guard is only for the UX

A route sets `data.permission` or `data.gremiumPermission`. A missing permission opens
`/forbidden`. The backend must enforce the same right.
