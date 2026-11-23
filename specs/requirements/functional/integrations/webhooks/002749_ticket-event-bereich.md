---
id: "002749"
title: The ticket event names the Bereich and follows the Gremium filter
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_webhooks.py:test_created_follows_the_gremium_filter"
  - "backend/tests/unit/modules/tickets/test_ticket_webhooks.py:test_created_names_the_area_and_the_source"
implementation:
  - backend/app/modules/tickets/webhook_fields.py
  - backend/app/modules/webhooks/catalog.py
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/tickets
---

# The ticket event names the Bereich and follows the Gremium filter

The event `ticket.created` must occur for a new ticket of each source. Its payload fields must
include the name of the Bereich and the source. The event must carry the Gremium of the Bereich,
so that the Gremium filter of a webhook holds for it (002414). A ticket of a Bereich without a
Gremium must pass that filter.

Reason: A Gremium sends its new tickets to its own chat without the tickets of the other teams.

Test: A unit test creates a ticket in a Bereich of Gremium A for a webhook with the filter
Gremium B and expects no delivery.
