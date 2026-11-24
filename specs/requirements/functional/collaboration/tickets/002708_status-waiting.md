---
id: "002708"
title: A ticket has the status Wartet auf Antwort
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_waiting.py:test_waiting_is_an_open_status_without_a_close_time"
  - "frontend/src/app/pages/tickets/tickets.util.spec.ts:tickets.util"
implementation:
  - backend/app/modules/tickets/models.py
  - backend/app/modules/tickets/service/changes.py
  - backend/app/modules/tickets/service/base.py
  - backend/migrations/versions/a8c3f15d7e42_ticket_waiting_source.py
  - frontend/src/app/pages/tickets/tickets.util.ts
  - frontend/src/app/pages/tickets/ticket-detail.component.ts
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A ticket has the status Wartet auf Antwort

A ticket must have exactly one of the statuses `Neu`, `In Bearbeitung`, `Wartet auf Antwort`,
`Erledigt` and `Abgelehnt`. `Wartet auf Antwort` must not start the retention time.

Reason: A helpdesk must tell the tickets that wait for the team from the tickets that wait for
the sender.

Test: A unit test sets `Wartet auf Antwort` and expects an empty `closed_at`.
