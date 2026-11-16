---
id: "001071"
title: A person added to a free board by name gets a mail
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/todos/test_todos_free_boards.py:test_only_the_permission_creates_a_free_board"
implementation:
  - backend/app/modules/todos/mails.py
  - backend/app/modules/notifications/texts/todos.py
scope:
  - backend/app/modules/todos
  - backend/app/modules/notifications
---

# A person added to a free board by name gets a mail

A person who is added as a person entry to a free board must get the mail `todo_board_added` with
the name of the board, the role and a link to the board. The actor must get no mail. A Gremium
entry must send no mail to the members of the Gremium. The mail must be an opt-out kind.

Reason: A person must learn of a new board, but a whole Gremium must not get a mail for each
board (the rule of 000325 against mail spam).

Test: A backend test adds a person and a Gremium and finds one mail.
