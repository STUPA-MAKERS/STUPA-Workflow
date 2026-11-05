---
id: "000111"
title: A member with an active delegation is not present
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/delegations
  - frontend/src/app/features/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# A member with an active delegation is not present

A member with an active delegation cannot report "present", and the lead cannot set them
present. Both answer 409 `delegation_active` until the delegation is revoked.
