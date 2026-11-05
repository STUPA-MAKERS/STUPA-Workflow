---
id: "000117"
title: Only a draft protocol is deleted
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
---

# Only a draft protocol is deleted

A protocol can be deleted only while it is a `draft`. A `final` or `rendering` protocol
answers 409.
