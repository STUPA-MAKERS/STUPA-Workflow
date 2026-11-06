---
id: "000403"
title: A webhook can be deleted
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/admin/router.py
  - backend/app/modules/admin/service/webhooks.py
  - frontend/src/app/pages/admin/config/webhooks.component.ts
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# A webhook can be deleted

A holder of `webhook.manage` must be able to delete a webhook. Its deliveries must go with it.
