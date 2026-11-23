---
id: "002414"
title: A webhook filters by Gremium, Antragsart and target status
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/webhooks/test_webhook_events.py:test_filters"
implementation:
  - backend/app/modules/webhooks/events.py
  - backend/app/modules/admin/service/webhooks.py
  - frontend/src/app/pages/admin/webhooks/webhooks.component.html
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/admin
  - frontend/src/app/pages/admin/webhooks
---

# A webhook filters by Gremium, Antragsart and target status

A webhook must hold an optional list of Gremien and an optional list of Antragsarten. An empty
list must let every value pass. An event with a Gremium must pass only when the Gremium is in the
list. An event with an Antragsart must pass only when the Antragsart is in the list. An event
without a Gremium or an Antragsart must pass that filter.

A webhook must also hold an optional list of target states for `application.transition`. An empty
list must let every status change pass. A non-empty list must let a status change pass only when
its target status is in the list.

Reason: A Gremium can get its own webhook without the events of other Gremien. The status filter
replaces the `webhook` action of the flow.

Test: A unit test lets an event of Gremium A occur for a webhook with the filter Gremium B and
checks that it gets no delivery.
