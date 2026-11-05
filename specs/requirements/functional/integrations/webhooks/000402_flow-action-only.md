---
id: "000402"
title: A webhook fires only through a flow action
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# A webhook fires only through a flow action

A webhook sends only when a flow transition runs its `webhook` action. A webhook has no event
subscription list.
