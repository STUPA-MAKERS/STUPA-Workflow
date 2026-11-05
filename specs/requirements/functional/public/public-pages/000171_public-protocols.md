---
id: "000171"
title: Only final protocols of public Gremien are public
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/public-protocols
---

# Only final protocols of public Gremien are public

A protocol is public only when it is final and its Gremium has `protocols_public`. A switch-on
publishes all final protocols of the Gremium. A protocol manager can hold one protocol back.
