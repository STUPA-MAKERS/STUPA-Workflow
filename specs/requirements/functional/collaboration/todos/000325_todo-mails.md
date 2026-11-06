---
id: "000325"
title: To-do mails go to assignees
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/notifications
  - backend/worker/mail.py
---

# To-do mails go to assignees

A new assignee must get `todo_assigned`, a new mention must get `todo_mentioned`, and the
assignees of an open card due tomorrow must get `todo_due` once. The actor must get no mail
about own actions.
