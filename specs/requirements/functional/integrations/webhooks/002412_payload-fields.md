---
id: "002412"
title: A webhook chooses the payload fields per event
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/webhooks/test_webhook_events.py:test_build_body_keeps_ids_and_drops_unknown_keys"
  - "backend/tests/unit/modules/admin/test_admin_service_cov.py:test_webhook_subscription_validation"
protocols:
  - "P/integrations/webhooks/000963"
implementation:
  - backend/app/modules/webhooks/events.py
  - backend/app/modules/admin/schemas.py
  - frontend/src/app/pages/admin/webhooks/webhooks.component.ts
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
