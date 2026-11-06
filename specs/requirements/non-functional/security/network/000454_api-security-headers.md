---
id: "000454"
title: The API sends strict security headers and no CORS
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/middleware.py
scope:
  - backend/app/middleware.py
---

# The API sends strict security headers and no CORS

Every API answer must carry `Content-Security-Policy: default-src 'none'`, `X-Frame-Options:
DENY`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. The app must not
register CORS.

Reason: The API serves only JSON, and cross-origin access stays off.
