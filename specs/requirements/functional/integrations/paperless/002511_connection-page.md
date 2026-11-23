---
id: "002511"
title: An admin connects one Paperless instance
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---

# An admin connects one Paperless instance

The admin page `Paperless` must hold the address and the token of one Paperless-ngx instance.
The page must have a button that tests the connection and shows the result. The page must need
the permission `admin.paperless`.

Reason: The integration works with each Paperless-ngx instance, so the operator of a platform
sets the connection in the platform.

Test: A unit test saves a connection without the permission and expects 403.
