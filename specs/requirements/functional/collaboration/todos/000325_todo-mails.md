---
id: "000325"
title: To-do mails go to assignees
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/notifications
  - backend/worker/mail.py
---

# To-do mails go to assignees

A new assignee gets `todo_assigned`, a new mention gets `todo_mentioned`, and the assignees of
an open card due tomorrow get `todo_due` once. The actor gets no mail about own actions.
