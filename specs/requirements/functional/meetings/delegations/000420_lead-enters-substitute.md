---
id: "000420"
title: The lead can enter a pool substitute
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/delegations/pool_seat.py
  - frontend/src/app/features/meetings/lead-substitute-dialog/lead-substitute-dialog.component.ts
scope:
  - backend/app/modules/delegations
  - backend/app/modules/livevote
---

# The lead can enter a pool substitute

During a live meeting, the lead must be able to enter a pool substitute for an absent member.
