---
id: "000276"
title: Tokens never reach JavaScript
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - frontend/src/app/core/auth
---

# Tokens never reach JavaScript

A session token must live only in an HttpOnly, Secure, SameSite=Lax cookie. A response body
must never hold a session token. A magic-link token must be in the URL fragment.

Reason: The fragment stays out of the Referer, the logs and the history.
