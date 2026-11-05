---
id: "000066"
title: Public endpoints are a fixed list
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
---

# Public endpoints are a fixed list

An endpoint without login must be in `PUBLIC_ROUTES`. Every other route needs a login.

Test: `backend/tests/unit/test_public_routes.py`
