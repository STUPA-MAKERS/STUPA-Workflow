---
id: "002764"
title: A Paperless link needs the Paperless permission
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---

# A Paperless link needs the Paperless permission

A person must be able to add or remove a link with a Paperless end only with the permission
`paperless.use` and the change right of the other element (F/collaboration/links/001404). A
person without `paperless.use` must see the end as `Paperless-Dokument (kein Zugriff)`, without
title, address or detail (001405). The link search must not offer the kind to that person, and a
card must not give read access to a Paperless end (F/collaboration/todos/000487). No OAuth scope
must reach the kind (002524).

Reason: The title of a document in the archive can be confidential. The link follows the same
rule as the search and the entry `In Paperless öffnen`.

Test: A backend unit test reads the links of an Antrag with and without `paperless.use`, and
adds a link without the permission and gets 403.
