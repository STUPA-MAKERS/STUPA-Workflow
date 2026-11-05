---
id: "000393"
title: Database roles are separated
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - deploy/
  - backend/alembic
---

# Database roles are separated

The migrations use the `migrator` role. The runtime uses the `app` role with DML only. The
audit table is append-only for the runtime.
