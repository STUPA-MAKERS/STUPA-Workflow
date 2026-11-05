---
id: "000048"
title: A plain pytest skips integration tests
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/
---

# A plain pytest skips integration tests

Run `pytest -m integration` before you push backend work that touches the database. A plain
`pytest` deselects the integration tests.
