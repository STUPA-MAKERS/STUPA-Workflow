---
id: "000352"
title: A guest joins with one device
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/livevote
---

# A guest joins with one device

A guest join needs an ALTCHA and has a rate limit per IP and per code. One device has one
token, in an HttpOnly, SameSite=Strict cookie.
