---
id: "000179"
title: A public route is on the allowlist
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/deps.py
scope:
  - backend/app/
---

# A public route is on the allowlist

A route without login must be in `PUBLIC_ROUTES`. Every other route must need a session or a
token. A route that reads one object must check the access to that object.

Test: `tests/unit/test_public_routes.py` and `tests/unit/test_route_gates.py`.
