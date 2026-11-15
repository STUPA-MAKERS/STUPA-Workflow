---
id: "000117"
title: Only a draft protocol is deleted
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/protocol/service.py
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
---

# Only a draft protocol is deleted

A protocol must be deletable only while it is a `draft` that was never final. A `final` or
`rendering` protocol must answer 409, and so must a draft that went back from final (000983),
because the members got its PDF by mail.
