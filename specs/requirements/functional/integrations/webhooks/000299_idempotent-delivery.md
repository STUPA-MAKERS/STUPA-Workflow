---
id: "000299"
title: A delivery runs once per key
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/webhooks
---

# A delivery runs once per key

A delivery must be unique per webhook and idempotency key. A duplicate dispatch must create no
second delivery.
