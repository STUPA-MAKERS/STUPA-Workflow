---
id: "001065"
title: Assignees of a free board are its members who edit
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/app/modules/todos/access.py
scope:
  - backend/app/modules/todos
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# Assignees of a free board are its members who edit

The members of a free board, for assignees and mentions (000320), must be the persons with the
role `Bearbeiten` or `Verwalten` through an entry of a person or of a Gremium. A person with only
`Lesen` must not be assigned or mentioned. The mails of 000325 must follow the same members.

Reason: A card must not be given to a person who cannot work on it.

Test: A backend test assigns a reader and gets 422 `assignee_not_allowed`.
