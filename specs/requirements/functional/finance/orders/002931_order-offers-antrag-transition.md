---
id: "002931"
title: A status change of a Bestellung offers a transition of the Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/pages/orders/order-detail.component.ts
  - frontend/src/app/pages/admin/flow/transition-detail.component.ts
scope:
  - backend/app/modules/flow
  - backend/app/modules/orders
  - frontend/src/app/pages/applications
  - frontend/src/app/pages/admin
---

# A status change of a Bestellung offers a transition of the Antrag

A transition of the flow can carry the setting `offerOnOrderStatus` with the value "Bestellt"
or "Geliefert". An admin sets it in the flow editor. When a person sets a Bestellung to this
status, the frontend must offer each transition with this setting that leaves the current state
of the Antrag and that this person can fire. The person fires the transition or closes the
offer. The platform must not fire the transition by itself. The code must not name a state or a
transition of a flow.

Reason: The status of the Antrag often follows the purchase, and the offer saves the second
step. The flow is the configuration of each installation, so only a setting on the transition
can say which transition fits.

Test: A backend unit test reads the offered transitions for a flow with the setting, for a flow
without it and for a person who cannot fire the transition. A frontend unit test sets the
status, reads the offer, closes it and reads no call of the transition.
