---
name: run-integration-before-push
description: A plain pytest deselects the integration tests, and they share one Postgres. Run pytest -m integration before a push
metadata:
  node_type: memory
  type: feedback
---

The rules are specs in `specs/` of the STUPA-Workflow repository. Read the spec, not this
file:

- `S/shared/testing/000048` CI runs the full suites
- `S/shared/testing/000047` An integration test uses its own keys
