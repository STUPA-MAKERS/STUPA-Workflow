---
id: "000128"
title: The timeline links the deciding vote
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/applications/service/reads.py
  - frontend/src/app/pages/applications/applications-detail.component.ts
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The timeline links the deciding vote

A status event must link the vote that decided it. The detail must show "Zur Abstimmung".
