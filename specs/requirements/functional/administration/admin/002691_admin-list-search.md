---
id: "002691"
title: The search of a Verwaltung list finds the text of a row
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/src/app/pages/admin/list-search.spec.ts:listSearch"
  - "backend/tests/unit/modules/auth/test_oauth_admin_grants.py:test_list_grants_search"
implementation:
  - frontend/src/app/pages/admin/list-search.ts
  - backend/app/modules/auth/oauth_admin_router.py
scope:
  - frontend/src/app/pages/admin
  - backend/app/modules/auth
---

# The search of a Verwaltung list finds the text of a row

The search of a list page of Verwaltung (002690) must show only the rows whose shown texts
contain each word of the search, without regard to case. The shown texts are the title, the
second line and the status of the row. The search must run while the person types, and the
filter chips must still apply.

A list that loads all its rows at once must filter in the browser. A list that loads page by
page (Agent-Zugänge) must send the search to the server as `q`, and the server must search the
same texts (name, e-mail, client and scope of a grant).

An empty result must show the empty state "Keine Treffer" of the search.

Reason: A search over only the loaded page of a paged list misses rows, while a request per key
press is not needed for a list that is already complete.

Test: A unit test of `listSearch` checks words, case and an empty search. A backend test of the
grant list checks `q`.
