---
id: "002920"
title: The scope paperless:use carries only paperless.use
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "backend/tests/unit/modules/auth/test_paperless_scope.py:test_the_scope_carries_only_paperless_use"
  - "backend/tests/unit/modules/auth/test_paperless_scope.py:test_the_consent_shows_the_scope_only_to_a_holder"
  - "backend/tests/integration/modules/todos/test_paperless_links.py:test_a_token_links_only_with_the_paperless_scope"
implementation:
  - backend/app/modules/auth/oauth.py
  - backend/app/modules/auth/oauth_router.py
  - frontend/src/app/core/i18n/catalog/de.json
  - frontend/src/app/core/i18n/catalog/en.json
  - mcp/antragsplattform_mcp/config.py
scope:
  - backend/app/modules/auth
  - backend/app/modules/todos
  - backend/app/modules/paperless_filing
  - frontend/src/app/pages/account
  - mcp/
---

# The scope paperless:use carries only paperless.use

The OAuth scope `paperless:use` must carry exactly the permission `paperless.use`. The default
scope of the server and of the MCP must not hold it, so a client must ask for it by name. The
consent page must show it with its own text in German and English, and only to a person who
holds `paperless.use`. A token with the scope must reach these routes, under the rules of
002764 and F/collaboration/links/001404:

- `POST /api/links`, `GET /api/links` and `DELETE /api/links/{id}` with a Paperless end
- `GET /api/links/targets?kind=paperless`
- `GET /api/paperless/documents/{kind}/{id}`

A token without the scope must get 403 there as before (`link_forbidden` or `forbidden`). No
scope must carry `admin.paperless`.

Reason: An agent links many Paperless documents with invoices, Buchungen and Anträge, and a
person must not do each link in the browser. The archive can hold confidential documents, so the
owner of the token gives this right on purpose.

Test: A backend unit test resolves the scope, and an integration test adds a Paperless link with
a token with and without the scope.
