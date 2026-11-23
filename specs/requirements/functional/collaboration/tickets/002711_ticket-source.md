---
id: "002711"
title: A ticket names its source
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A ticket names its source

A ticket must store its source: the help menu, a mail, or a person of the team. The detail view
of the team must show the source.

Reason: The source decides how an answer reaches the sender: in the app, or as a mail (002733).

Test: A unit test creates one ticket on each way and expects the three sources.
