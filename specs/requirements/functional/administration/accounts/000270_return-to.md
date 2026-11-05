---
id: "000270"
title: The login returns to the page
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - frontend/src/app/core/auth
---

# The login returns to the page

The login returns to the page that the user came from. The server keeps `returnTo` only if it
is a local path outside `/api/`, at most 1024 characters long.
