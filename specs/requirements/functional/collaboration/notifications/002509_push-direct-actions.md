---
id: "002509"
title: A push can act without opening the app
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation:
  - backend/app/modules/notifications
  - backend/app/modules/push_actions/router.py
scope:
  - backend/app/modules/notifications
  - frontend/src/app/core/pwa
---

# A push can act without opening the app

A push about a Termin invitation must carry the buttons "Zusagen" and "Absagen". A push about an
assigned or due to-do, or a mention in a to-do, must carry the button "Erledigt". Such a button
must act in the background through a signed token in the push. The token must name the person,
the action and the element, must be valid for seven days, and must allow nothing else. The
action must check the rights of the person as the app does. A vote must never be cast from a
push.

Reason: These are the most common one-tap answers; a vote is secret and needs a confirmation.

Test: `backend/tests/unit/modules/notifications/test_push_pure.py`,
`backend/tests/integration/modules/todos/test_push_todo_done.py`,
`backend/tests/integration/modules/calendar/test_push_answer.py`.
