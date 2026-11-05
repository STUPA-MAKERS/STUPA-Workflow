---
id: "000068"
title: A migration has a hash ID
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/migrations/
---

# A migration has a hash ID

Make a new revision with `alembic revision -m "..."`. Do not use `--rev-id`. A revision ID
must have at most 32 characters.

Reason: `alembic_version` is `varchar(32)`. A longer ID fails only at the deploy.
