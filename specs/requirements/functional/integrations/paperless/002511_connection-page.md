---
id: "002511"
title: An admin connects one Paperless instance
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_the_connection_saves_and_no_read_returns_the_token"
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_the_admin_routes_need_the_admin_permission"
  - "frontend/src/app/pages/admin/paperless/paperless.component.spec.ts:PaperlessComponent"
implementation:
  - backend/app/modules/paperless/connection.py
  - backend/app/modules/paperless_filing/router.py
  - frontend/src/app/pages/admin/paperless
scope:
  - backend/app/
  - frontend/src/app/
---

# An admin connects one Paperless instance

The admin page `Paperless` must hold the address, the optional address for links (002844) and
the token of one Paperless-ngx instance.
The page must have a button that tests the connection and shows the result. The page must need
the permission `admin.paperless`.

Reason: The integration works with each Paperless-ngx instance, so the operator of a platform
sets the connection in the platform.

Test: A unit test saves a connection without the permission and expects 403.
