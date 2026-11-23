---
id: "002766"
title: The link search finds Paperless documents
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/todos/test_paperless_links.py:test_an_outage_keeps_the_stored_title_and_the_other_hits"
  - "frontend/src/app/features/todos/link-picker/todo-link-picker.component.spec.ts:TodoLinkPickerComponent"
implementation:
  - backend/app/modules/todos/links.py
  - backend/app/modules/todos/links_router.py
  - frontend/src/app/features/todos/link-picker/todo-link-picker.component.ts
scope:
  - backend/app/
  - frontend/src/app/
---

# The link search finds Paperless documents

The search of `Verknüpfen` (F/collaboration/links/001408) must have the kind `Paperless` for a
person with `paperless.use` while the part is on. With that kind chosen, the search must ask
Paperless as the Paperless search does (002529, 002534): title and content, at most 20 hits, and
the newest documents without a search term. The search over all kinds must add the hits of
Paperless as the last group. When Paperless fails, the search must show the hits of the other
kinds, and the group must show `Paperless ist nicht erreichbar`.

Reason: One picker for every kind (001408). An outage of the archive must not block the links
between elements of the platform.

Test: A frontend unit test picks the kind and links a hit. A backend unit test lets Paperless
fail and gets the hits of the other kinds.
