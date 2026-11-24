---
id: "002923"
title: Each added or removed link has an audit entry
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "backend/tests/integration/modules/todos/test_paperless_links.py:test_the_audit_names_the_grant"
implementation:
  - backend/app/modules/todos/link_audit.py
  - backend/app/modules/todos/link_service.py
  - backend/app/modules/audit/actions.py
  - backend/app/modules/auth/principal.py
  - backend/app/deps.py
scope:
  - backend/app/modules/todos
  - backend/app/modules/audit
  - backend/app/modules/auth
  - frontend/src/app/pages/admin
---

# Each added or removed link has an audit entry

The platform must write an audit entry `link_add` or `link_remove` for each link that a person
or a token adds or removes, of every kind. The entry must name both ends by kind and id, and a
Paperless end also by its document number. When a token makes the change, the entry must name
the grant (the id of the token and its client). The audit log must show the action with its own
text.

Reason: An agent can add many links in a short time. The audit log must show which token made a
link, so an admin can revoke that token and find its links.

Test: A backend test adds and removes a link with a token and reads the grant in both entries.
