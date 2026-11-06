---
id: "000362"
title: A delegation belongs to one meeting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/delegations/service.py
  - backend/app/modules/delegations/models.py
scope:
  - backend/app/modules/delegations
---

# A delegation belongs to one meeting

A delegation must target one meeting. The Gremium and the validity must come from the meeting.
An old period delegation must never count for a vote.
