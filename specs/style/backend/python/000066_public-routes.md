---
id: "000066"
title: Public endpoints are a fixed list
kind: style
status: replaced
owner: frederikbeimgraben
updated: 2026-11-06
replaced_by: NF/security/access/000179
scope:
  - backend/app/
---

# Public endpoints are a fixed list

An endpoint without login must be in `PUBLIC_ROUTES`. Every other route needs a login.

Test: `backend/tests/unit/test_public_routes.py`
