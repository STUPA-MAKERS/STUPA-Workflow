---
id: "000352"
title: A guest joins with one device
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote
scope:
  - backend/app/modules/livevote
---

# A guest joins with one device

A guest join must need an ALTCHA and must have a rate limit per IP and per code. One device
must have one token, in an HttpOnly, SameSite=Strict cookie.
