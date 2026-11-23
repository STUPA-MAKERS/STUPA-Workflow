---
id: "002410"
title: A webhook subscribes to events
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/webhooks/test_webhook_events.py:test_emit_one_delivery_per_subscriber"
protocols:
  - "P/integrations/webhooks/000963"
implementation:
  - backend/app/modules/webhooks/events.py
  - backend/app/modules/webhooks/models.py
  - backend/app/modules/applications/webhook_fields.py
  - backend/app/modules/voting/webhook_fields.py
  - backend/app/modules/livevote/webhook_fields.py
  - backend/app/modules/protocol/webhook_fields.py
  - backend/app/modules/budget/webhook_fields.py
  - backend/app/modules/tickets/webhook_fields.py
  - backend/app/modules/flow/service.py
  - backend/app/shared/guards.py
  - backend/migrations/versions/08e0c0134332_webhook_event_subscriptions.py
  - frontend/src/app/pages/admin/webhooks/webhooks.component.ts
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/admin
  - backend/app/modules/flow
  - frontend/src/app/pages/admin/flow
  - frontend/src/app/pages/admin/webhooks
---

# A webhook subscribes to events

A webhook must hold a list of subscribed events from the catalog in F/integrations/webhooks/002411.
When an event of the catalog occurs, the platform must create one delivery for each active webhook
that subscribes to the event and whose filters (F/integrations/webhooks/002414) let it pass. A
webhook with an empty list must send nothing through an event.

The flow must have no `webhook` action. A webhook that must send at one status change subscribes
to `application.transition` and filters by the target status (F/integrations/webhooks/002414). The
migration must turn each existing `webhook` action into such a subscription: the webhook gets the
event `application.transition` with the target states of all transitions that named it, and the
action is removed from the flow.

Reason: An admin chooses per receiver which changes it gets, in one place. A second way to send
from the flow editor would split the config.

Test: A unit test lets each catalog event occur for two webhooks, one that subscribes and one that
does not, and checks that only the first gets a delivery.
