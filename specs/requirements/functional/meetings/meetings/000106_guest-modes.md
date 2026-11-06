---
id: "000106"
title: Guests vote or only watch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote/guests.py
  - frontend/src/app/features/meetings/public-join/public-join-settings.component.ts
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# Guests vote or only watch

A meeting with guests must be in the mode "Gäste dürfen abstimmen" or "nur zuschauen". The mode
must not change from vote to watch while a vote with guests is open.
