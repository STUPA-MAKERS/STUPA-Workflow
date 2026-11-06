---
id: "000270"
title: The login returns to the page
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - frontend/src/app/core/auth
---

# The login returns to the page

The login must return to the page that the user came from. The server must keep `returnTo` only
if it is a local path outside `/api/` with at most 1024 characters.
