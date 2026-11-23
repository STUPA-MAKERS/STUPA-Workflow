---
id: "002412"
title: A webhook chooses the payload fields per event
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
  - frontend/src/app/pages/admin/webhooks
---

# A webhook chooses the payload fields per event

For each subscribed event, a webhook must hold a list of field keys from the field catalog of the
event in P/integrations/webhooks/000963. The `data` object of a delivery must hold exactly the
chosen fields. The event name, `occurredAt` and the ID keys of the event must always be in the
body. The API must refuse a field key that the event does not have with `422`.

Reason: The admin decides which information leaves the platform, field by field.

Test: A unit test chooses two fields for an event and checks that `data` holds exactly these two.
