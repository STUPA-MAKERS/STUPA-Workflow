---
id: "000394"
title: A deploy runs the migration first
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - deploy/docker-compose.yml
scope:
  - deploy/
---

# A deploy runs the migration first

The one-shot `migrate` service must run `alembic upgrade head`. `api` and `worker` must start
only after it succeeded.
