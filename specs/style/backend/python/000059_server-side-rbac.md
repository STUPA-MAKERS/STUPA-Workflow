---
id: "000059"
title: Permissions are checked on the server
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/
scope:
  - backend/app/
---

# Permissions are checked on the server

The backend must check every permission. Roles and owner come from the session, never from
the request body. A global permission is a route gate (`require_principal("perm")`). A
Gremium permission goes into `app/modules/auth/policy.py`. An object rule is a bare gate plus
an entry in `OBJECT_CHECK_ROUTES`.

Test: `backend/tests/unit/test_route_gates.py`
