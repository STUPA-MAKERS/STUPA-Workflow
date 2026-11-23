---
id: "002416"
title: A webhook can send a test delivery
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/admin/test_admin_service_cov.py:test_send_test_delivery"
  - "backend/tests/unit/protocols/test_webhook_delivery.py:test_test_delivery_matches_schema"
protocols:
  - "P/integrations/webhooks/000963"
implementation:
  - backend/app/modules/admin/service/webhooks.py
  - backend/app/modules/admin/router.py
  - frontend/src/app/pages/admin/webhooks/webhooks.component.ts
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/admin
  - frontend/src/app/pages/admin/webhooks
---

# A webhook can send a test delivery

A holder of `webhook.manage` must be able to send a test delivery from the ⋮ menu of a webhook.
The test delivery must have the event `webhook.test`, must hold example values for every chosen
field of every subscribed event and must go through the same signature, SSRF guard and retry rules
as every other delivery. The delivery status of the webhook must show its result.

Reason: The admin can check the receiver and its signature check without a real event.

Test: A unit test sends a test delivery and validates the body against the schema of
P/integrations/webhooks/000963.
