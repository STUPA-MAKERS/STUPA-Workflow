---
id: "000098"
title: Agenda changes only while planned or live
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/meetings/agenda_service.py
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# Agenda changes only while planned or live

A person must add, remove and move an agenda item only while the meeting is `planned` or
`live`, else 409 `meeting_closed`. The title, the text and the mark "nicht öffentlich" of an
agenda item follow 000982. A TOP with an open or closed vote must not be deletable.
