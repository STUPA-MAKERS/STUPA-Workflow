---
id: "000186"
title: The login audit has no plain IP address
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/modules/audit
---

# The login audit has no plain IP address

An audit entry for a login must not store the IP address in plain text.
