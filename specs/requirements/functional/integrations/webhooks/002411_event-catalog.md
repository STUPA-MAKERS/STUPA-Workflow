---
id: "002411"
title: The webhook events come from a fixed catalog
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/webhooks/test_webhook_events.py:test_catalog_matches_the_event_names"
protocols:
  - "P/integrations/webhooks/000963"
implementation:
  - backend/app/modules/webhooks/catalog.py
  - backend/app/modules/admin/schemas.py
  - backend/app/modules/admin/service/webhooks.py
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/admin
  - frontend/src/app/pages/admin/webhooks
---

# The webhook events come from a fixed catalog

A webhook must subscribe only to the events in this table. The API must refuse an unknown event
name with `422`.

| Event | Group | Occurs when |
| --- | --- | --- |
| `application.created` | Anträge | An Antrag is submitted or captured on behalf. |
| `application.updated` | Anträge | The data of an Antrag is edited (new version). |
| `application.transition` | Anträge | The status of an Antrag changes through a transition. |
| `application.archived` | Anträge | An Antrag is archived. |
| `comment.created` | Anträge | A comment on an Antrag is written. |
| `vote.opened` | Abstimmungen | A vote opens. |
| `vote.closed` | Abstimmungen | A vote closes with a result. |
| `meeting.created` | Sitzungen | A meeting is created. |
| `meeting.started` | Sitzungen | A meeting starts. |
| `meeting.closed` | Sitzungen | A meeting closes. |
| `protocol.finalized` | Protokolle | A protocol is final. |
| `booking.created` | Haushalt | A booking is made: an expense, an income or a transfer. |
| `invoice.created` | Haushalt | An invoice is created or imported. |
| `ticket.created` | Tickets | A ticket is new: from the help menu, a mail or the team. |
| `ticket.message` | Tickets | The sender of a ticket writes one more message. |
| `ticket.status` | Tickets | The status of a ticket changes. |

The ID keys and the fields of each event are in P/integrations/webhooks/000963.

Reason: A fixed catalog gives the receiver a stable contract and lets the server validate the
config. Internal admin and config events stay out, because they are in the audit log.

Test: A unit test sends an unknown event name to the create route and expects `422`.
