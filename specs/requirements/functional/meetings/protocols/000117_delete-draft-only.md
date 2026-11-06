---
id: "000117"
title: Only a draft protocol is deleted
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
---

# Only a draft protocol is deleted

A protocol must be deletable only while it is a `draft`. A `final` or `rendering` protocol must
answer 409.
