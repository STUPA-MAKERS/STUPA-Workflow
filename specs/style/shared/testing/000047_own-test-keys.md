---
id: "000047"
title: An integration test uses its own keys
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/tests/integration/
---

# An integration test uses its own keys

An integration test that writes rows keyed by a constant (client id, slug, name) must use a
value of its own. Do not widen the assertion of a different test.

Reason: All integration tests share one Postgres container, so shared keys make a test fail
only in CI.
