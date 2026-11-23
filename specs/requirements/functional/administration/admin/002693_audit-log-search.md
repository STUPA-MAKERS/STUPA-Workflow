---
id: "002693"
title: The Audit-Log searches on the server
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/audit/test_audit_service_cov.py:test_query_cursor_search_matches_each_word"
  - "backend/tests/unit/modules/audit/test_audit_service_cov.py:test_query_cursor_search_adds_the_label_actions"
  - "backend/tests/unit/modules/audit_log/test_audit_log_router.py:test_list_passes_the_search"
  - "backend/tests/unit/modules/auth/test_identity.py:test_subs_named_matches_own_and_merged_names"
  - "frontend/src/app/pages/admin/audit/audit-log.component.spec.ts:AuditLogComponent"
implementation:
  - backend/app/modules/audit/service.py
  - backend/app/modules/audit_log/router.py
  - backend/app/modules/auth/identity.py
  - frontend/src/app/pages/admin/audit/audit-log.component.ts
scope:
  - backend/app/modules/audit
  - backend/app/modules/audit_log
  - frontend/src/app/pages/admin/audit
---

# The Audit-Log searches on the server

The Audit-Log page must have the search pill of the Verwaltung lists (002690) above its filter
chips. The log loads page by page, so the page must send the search to the server as `q`, and
the filter chips must still apply.

An entry must match when each word of the search occurs, without regard to case, in its action
key, its actor (`sub`, name or e-mail, also the name of an account that it was merged into), its
target type or id, or its data. The action labels live in the frontend, so the page must also
send as `labelAction` each action key whose shown label holds every word, and an entry with such
an action must match as well.

The search must run after a short pause in typing and at once on Enter. A new search or filter
must cancel a load in flight. The pill must show the number of hits once no further page
follows. An empty result must show "Keine Treffer".

Reason: The log is too long to load in the browser, and a person searches for the labels that
the page shows, not for the stored keys.

Test: Backend unit tests check the search clause, the label actions and the actor names. The
component spec checks the request, the pause, the hit count and the empty result.
