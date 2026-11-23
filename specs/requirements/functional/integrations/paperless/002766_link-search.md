---
id: "002766"
title: The link search finds Paperless documents
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
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
