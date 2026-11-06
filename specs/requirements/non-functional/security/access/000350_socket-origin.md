---
id: "000350"
title: A meeting socket checks the origin
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/livevote
---

# A meeting socket checks the origin

A meeting socket authenticates from the session cookie and checks the `Origin` against an
allowlist. A person has at most 5 sockets per meeting, with a frame rate limit. A cast on an
open socket checks again that the account is active and not merged.
