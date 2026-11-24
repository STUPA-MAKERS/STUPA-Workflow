---
id: "002764"
title: A Paperless link needs the Paperless permission
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "backend/tests/integration/modules/todos/test_paperless_links.py:test_a_link_needs_the_permission"
  - "frontend/src/app/features/todos/linked-list/todo-linked-list.component.spec.ts:TodoLinkedListComponent"
implementation:
  - backend/app/modules/todos/link_rights.py
  - backend/app/modules/todos/link_service.py
  - backend/app/modules/todos/links.py
scope:
  - backend/app/
  - frontend/src/app/
---

# A Paperless link needs the Paperless permission

A person must be able to add or remove a link with a Paperless end only with the permission
`paperless.use` and the change right of the other element (F/collaboration/links/001404). A
person without `paperless.use` must see the end as `Paperless-Dokument (kein Zugriff)`, without
title, address or detail (001405). The link search must not offer the kind to that person, and a
card must not give read access to a Paperless end (F/collaboration/todos/000487). Only the OAuth scope
`paperless:use` must reach the kind (F/integrations/mcp/002920).

Reason: The title of a document in the archive can be confidential. The link follows the same
rule as the search and the entry `In Paperless öffnen`.

Test: A backend unit test reads the links of an Antrag with and without `paperless.use`, and
adds a link without the permission and gets 403.
