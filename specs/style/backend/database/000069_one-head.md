---
id: "000069"
title: Alembic has one head
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/migrations/
---

# Alembic has one head

`alembic heads` must show exactly one head. If two pull requests add a migration on the same
parent, the pull request that merges second points its `down_revision` to the first.

Test: `alembic heads`
