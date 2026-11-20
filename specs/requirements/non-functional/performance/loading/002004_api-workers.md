---
id: "002004"
title: The API serves requests in four processes
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "backend/tests/unit/test_api_workers.py:test_the_api_starts_four_workers_by_default"
implementation:
  - backend/Dockerfile
  - deploy/.env.example
scope:
  - backend/Dockerfile
  - deploy/
---

# The API serves requests in four processes

The API container must start `API_WORKERS` uvicorn processes, and 4 when the variable is not
set. A state that more than one request shares must live in Redis or in the database, not in
the memory of one process. Only the caps of open WebSocket connections may count per process.

Reason: One process served every request one after the other, so a slow read made every
person wait, most of all in a meeting with many members. The VM has 4 vCPUs. The live events,
the locks, the rate limits and the ALTCHA replay guard already go through Redis.

Test: A unit test reads the start command of the image and fails without `--workers` that
reads `API_WORKERS` with the default 4.
