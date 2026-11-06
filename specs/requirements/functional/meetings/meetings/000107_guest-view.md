---
id: "000107"
title: Guests see public TOPs only
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote/guests.py
  - frontend/src/app/features/public-meeting/guest-view.component.ts
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# Guests see public TOPs only

A guest must see the participant view. A non-public TOP must show only its title. A guest must
never see attendance or delegations.
