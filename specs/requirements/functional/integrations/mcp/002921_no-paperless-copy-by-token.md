---
id: "002921"
title: A token does not copy documents into or out of Paperless
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "backend/tests/unit/modules/paperless/test_paperless_token.py:test_a_token_does_not_insert_or_file"
implementation:
  - backend/app/modules/paperless_filing/router.py
  - backend/app/modules/protocol/documents_router.py
  - backend/app/modules/tickets/router.py
scope:
  - backend/app/modules/paperless_filing
  - backend/app/modules/protocol
  - backend/app/modules/tickets
  - mcp/
---

# A token does not copy documents into or out of Paperless

An OAuth token must get 403 `cookie_session_required` at these routes, also with the scope
`paperless:use` (002920):

- `GET /api/paperless/insert` and `GET /api/paperless/search`
- `POST /api/meetings/{id}/documents/paperless` (the copy into a protocol text)
- `POST /api/tickets/{id}/files/{attachmentId}/paperless` (the filing of a ticket file)

Reason: Each of these routes copies a document into the platform or into the archive. The scope
gives the links and the address of a document only.

Test: A backend test calls each route with a token with the scope and expects 403.
