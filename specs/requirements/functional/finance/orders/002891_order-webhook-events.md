---
id: "002891"
title: The create and the status change of a Bestellung are webhook events
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/orders
---

# The create and the status change of a Bestellung are webhook events

The event catalog (F/integrations/webhooks/002411) must hold the events `order.created` and
`order.status_changed`. The payload fields must be the number, the Bezeichnung, the kind, the
status, the status before, the Händler, the prices and the id and the title of the Antrag. The
Gremium filter and the Antragsart filter of a webhook must use the Gremium and the type of the
Antrag.

Reason: A chat or an inventory tool wants to know that goods arrived. The filters of the Antrag
keep the events of one Gremium apart.

Test: A backend unit test emits both events and checks the payload and the Gremium filter.
