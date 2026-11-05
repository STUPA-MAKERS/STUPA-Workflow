---
id: "000070"
title: A migration that adds a table is idempotent
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/migrations/
---

# A migration that adds a table is idempotent

Use `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS` and `DROP TABLE IF EXISTS`.

Reason: The baseline builds the schema from the models, so the table already exists on a
fresh database.
