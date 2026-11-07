---
id: "000540"
title: A to-do can repeat
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-07
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# A to-do can repeat

A to-do card with a due date can carry a repeat rule: every N days, weeks, months or years,
with N from 1 to 99. An Event and a Beschaffung must not carry a repeat rule. The card must
show the rule next to the due date. `Wiederholung beenden` must remove the rule.

Reason: Duties such as the Rechenschaftsbericht, the Haushaltsplan or the Kassenprüfung come back on a fixed interval. Events have `Folgeveranstaltung anlegen` instead.

Test: A backend unit test gets 422 for a repeat rule on a card without a due date.
