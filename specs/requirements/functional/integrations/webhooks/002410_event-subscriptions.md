---
id: "002410"
title: A webhook subscribes to events
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
protocols:
  - "P/integrations/webhooks/000963"
implementation: null
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
