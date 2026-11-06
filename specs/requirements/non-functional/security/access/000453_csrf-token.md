---
id: "000453"
title: Cookie writes need the CSRF token
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/middleware.py
scope:
  - backend/app/middleware.py
---

# Cookie writes need the CSRF token

A write request with an auth cookie must carry the CSRF header that matches the CSRF cookie,
else it must answer 403 `csrf_failed`. A request with an `apat_` bearer token is exempt.

Reason: A cross-site page can send the cookie, but it cannot read the CSRF cookie or set the
header.
