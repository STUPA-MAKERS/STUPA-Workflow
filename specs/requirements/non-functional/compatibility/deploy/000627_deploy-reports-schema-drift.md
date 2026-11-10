---
id: "000627"
title: A deploy reports a schema that differs from the models
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
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
