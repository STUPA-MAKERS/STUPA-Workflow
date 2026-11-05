---
id: "000322"
title: A transfer keeps what the target supports
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# A transfer keeps what the target supports

A card moved to another board keeps its links, comments, files, checklist and events. It keeps
a label only if the target has a label with the same name. It drops assignees who are not
members of the target.
