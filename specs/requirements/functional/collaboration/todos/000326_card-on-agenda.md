---
id: "000326"
title: A card can go on the agenda
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/meetings/agenda_service.py
  - backend/app/modules/todos/links.py
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/livevote
---

# A card can go on the agenda

A card of the board of the meeting Gremium can become a TOP. A card must be on the agenda at
most once.
