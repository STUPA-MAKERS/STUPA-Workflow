---
id: "000402"
title: A webhook fires only through a flow action
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/webhooks/models.py
  - backend/app/modules/admin/schemas.py
  - backend/app/modules/webhooks/service.py
  - backend/migrations/versions/08dfb2c28b9a_drop_webhook_events.py
  - frontend/src/app/pages/admin/webhooks/webhooks.component.html
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# A webhook fires only through a flow action

A webhook must send only when a flow transition runs its `webhook` action. A webhook must not
have an event subscription list.
