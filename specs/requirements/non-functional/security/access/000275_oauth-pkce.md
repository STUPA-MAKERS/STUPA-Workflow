---
id: "000275"
title: The OAuth flow needs PKCE and a loopback redirect
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# The OAuth flow needs PKCE and a loopback redirect

The OAuth server accepts only the `S256` PKCE method and an `http` loopback `redirect_uri`.
A code is single-use. A refresh rotates the token pair. An invalid redirect answers 400 and
never redirects.
