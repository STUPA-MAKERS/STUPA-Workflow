---
id: "000190"
title: A list reads its rows in one request
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/
  - frontend/src/app/
scope:
  - backend/app/
  - frontend/src/app/
---

# A list reads its rows in one request

A list must read its rows and their related data in one request, not one request per row.
