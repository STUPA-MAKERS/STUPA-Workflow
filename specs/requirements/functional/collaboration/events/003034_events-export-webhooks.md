---
id: "003034"
title: Veranstaltungen have an export and webhook events
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/events/router.py
  - backend/app/modules/webhooks/catalog.py
scope:
  - backend/app/modules/events
  - backend/app/modules/webhooks
  - frontend/src/app/pages/events
---

# Veranstaltungen have an export and webhook events

The page `Veranstaltungen` must have the action `Exportieren` in its ⋮ menu. It must give an
XLSX file of the Events of the current segment, search and chips that the person reads, with
the fields of 003023 and the totals of 000479. The export must need `finance.export`. The
webhook catalog must have the events `event.created`, `event.updated`, `event.status_changed`
and `event.deleted`, with payload fields and filters like the events of a Bestellung (002891).

Reason: The totals of the Events go to the finance report, and other systems, for example a
website or a chat, must learn about a new Event.

Test: A backend unit test exports two Events and reads their rows, and gets 403 without
`finance.export`. A backend unit test fires `event.created` on a create.
