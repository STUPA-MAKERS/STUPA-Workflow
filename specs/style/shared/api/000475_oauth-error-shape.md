---
id: "000475"
title: The OAuth token endpoint uses the RFC 6749 error shape
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/auth/oauth_router.py
---

# The OAuth token endpoint uses the RFC 6749 error shape

`/oauth/token` must answer errors in the JSON shape of RFC 6749 and must carry
`x-error-contract: oauth`. It is the one exception to 000042.

Reason: OAuth clients parse only the RFC 6749 shape.
