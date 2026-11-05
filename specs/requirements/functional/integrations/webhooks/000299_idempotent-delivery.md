---
id: "000299"
title: A delivery runs once per key
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/webhooks
---

# A delivery runs once per key

A delivery is unique per webhook and idempotency key. A duplicate dispatch creates no second
delivery.
