---
id: "000350"
title: A meeting socket checks the origin
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote/router.py
  - backend/app/shared/ws.py
scope:
  - backend/app/modules/livevote
---

# A meeting socket checks the origin

A meeting socket must authenticate from the session cookie and must check the `Origin` against
an allowlist. A person must have at most 5 sockets per meeting, with a frame rate limit. A cast
on an open socket must check again that the account is active and not merged.
