---
id: "000322"
title: A transfer keeps what the target supports
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

# A transfer keeps what the target supports

A card moved to another board must keep its links, comments, files, checklist and events. It
must keep a label only if the target has a label with the same name. It must drop assignees who
are not members of the target.
