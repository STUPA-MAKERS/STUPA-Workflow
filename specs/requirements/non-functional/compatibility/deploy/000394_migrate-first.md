---
id: "000394"
title: A deploy runs the migration first
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - deploy/
---

# A deploy runs the migration first

The one-shot `migrate` service runs `alembic upgrade head`. `api` and `worker` start only after
it succeeded.
