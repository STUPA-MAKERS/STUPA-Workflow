---
id: "002524"
title: One permission gives the use of Paperless
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_the_entry_opens_the_document_only_with_the_permission"
implementation:
  - backend/app/shared/permissions.py
  - backend/app/modules/paperless_filing/router.py
scope:
  - backend/app/
  - frontend/src/app/
---

# One permission gives the use of Paperless

The permission `paperless.use` must give the entry `In Paperless öffnen` (002525) and the
insert from Paperless (002527). No seeded role except the admin role must hold it.

Reason: Each person with the permission reads what the account of the platform reads in
Paperless. An admin must give that access on purpose.

Test: A unit test searches Paperless without the permission and expects 403.
