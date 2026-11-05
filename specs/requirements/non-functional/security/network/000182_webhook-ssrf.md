---
id: "000182"
title: Webhooks cannot reach internal addresses
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/webhooks
---

# Webhooks cannot reach internal addresses

A webhook target must not resolve to a private, loopback or link-local address. Every webhook
request must carry an HMAC signature.
