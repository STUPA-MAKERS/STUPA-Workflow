---
id: "000111"
title: A member with an active delegation is not present
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/delegations
  - frontend/src/app/features/meetings
  - backend/app/modules/livevote
---

# A member with an active delegation is not present

A member with an active delegation must not be able to report "present", and the lead must not
be able to set them present. Both must answer 409 `delegation_active` until the delegation is
revoked.
