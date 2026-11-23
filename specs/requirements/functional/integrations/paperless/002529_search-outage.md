---
id: "002529"
title: The Paperless search tells an outage and keeps the editor
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_the_search_tells_an_outage"
  - "backend/tests/unit/modules/paperless/test_client.py:test_search_times_out_with_a_cause_code"
  - "frontend/src/app/features/meetings/paperless-insert/paperless-insert.component.spec.ts:PaperlessInsertComponent"
implementation:
  - backend/app/modules/paperless/client.py
  - backend/app/modules/paperless_filing/router.py
  - frontend/src/app/features/meetings/paperless-insert/paperless-insert.component.ts
scope:
  - backend/app/
  - frontend/src/app/
---

# The Paperless search tells an outage and keeps the editor

The Paperless search (002534) must answer within 5 seconds. When Paperless does not answer in that time
or answers with an error, the search window must show `Paperless ist nicht erreichbar`. The editor must
keep its text and must accept input.

Reason: An outage of Paperless must not block the work on a protocol (000176).

Test: A unit test of the search route lets the client time out and expects 503
`paperless_unavailable`.
