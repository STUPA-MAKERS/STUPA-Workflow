---
id: "002813"
title: A change of the Paperless address needs the token again
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/paperless/connection.py
  - frontend/src/app/pages/admin/paperless
scope:
  - backend/app/modules/paperless
  - frontend/src/app/pages/admin/paperless
---

# A change of the Paperless address needs the token again

A change of the address of the Paperless connection must carry the token in the same request.
Without the token the change must answer 422 with the code `token_required` and must change
nothing.

Reason: The stored token must not follow a new address. Else a person with the admin page and
without the token can send it to another host of the allowlist (002515).

Test: A unit test changes the address without a token and expects 422 `token_required` and the
old address.
