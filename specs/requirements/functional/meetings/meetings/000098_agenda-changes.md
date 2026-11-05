---
id: "000098"
title: Agenda changes only while planned or live
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# Agenda changes only while planned or live

The agenda changes only while the meeting is `planned` or `live`, else 409. A TOP with an open
or closed vote cannot be deleted.
