---
id: "000402"
title: A webhook fires only through a flow action
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# A webhook fires only through a flow action

A webhook must send only when a flow transition runs its `webhook` action. A webhook must not
have an event subscription list.
