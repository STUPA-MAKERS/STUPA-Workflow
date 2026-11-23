---
id: "002708"
title: A ticket has the status Wartet auf Antwort
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
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
