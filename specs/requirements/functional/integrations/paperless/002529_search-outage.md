---
id: "002529"
title: The Paperless search tells an outage and keeps the editor
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---

# The Paperless search tells an outage and keeps the editor

The search of 002527 must answer within 5 seconds. When Paperless does not answer in that time
or answers with an error, the list must show `Paperless ist nicht erreichbar`. The editor must
keep its text and must accept input.

Reason: An outage of Paperless must not block the work on a protocol (000176).

Test: A unit test of the search route lets the client time out and expects 503
`paperless_unavailable`.
