---
id: "000627"
title: A deploy reports a schema that differs from the models
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "backend/tests/integration/test_schema_drift.py:test_hand_made_check_constraint_is_logged_as_error"
  - "backend/tests/unit/shared/test_schema_drift.py:test_main_logs_each_difference_as_error_and_does_not_stop"
implementation:
  - backend/app/shared/schema_drift.py
  - deploy/docker-compose.yml
scope:
  - backend/migrations
  - deploy/
---

# A deploy reports a schema that differs from the models

After `alembic upgrade head`, the `migrate` service must compare the schema of the database
with `Base.metadata`, with the compare of 000626. It must write each difference to the log
with the level `error`. A difference must not stop the deploy.

Reason: A database that came through old migrations can differ from a fresh database, and CI
sees only a fresh database and the schema of the last release. The log names the difference
before a request fails on it. A stop of the deploy would keep a fix from production.

Test: An integration test adds a check constraint to the database by hand and finds the log
line.
