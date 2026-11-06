---
id: "000327"
title: A link shows nothing without access
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# A link shows nothing without access

A link to an element that the viewer cannot read must show "kein Zugriff" without title, URL or
detail.
