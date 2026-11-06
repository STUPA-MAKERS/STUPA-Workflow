---
id: "000275"
title: The OAuth flow needs PKCE and a loopback redirect
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/auth
  - backend/app/deps.py
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# The OAuth flow needs PKCE and a loopback redirect

The OAuth server must accept only the `S256` PKCE method and an `http` loopback `redirect_uri`.
A code must be single-use. A refresh must rotate the token pair. An invalid redirect must
answer 400 and must never redirect.
