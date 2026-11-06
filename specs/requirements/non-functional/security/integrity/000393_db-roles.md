---
id: "000393"
title: Database roles are separated
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - deploy/
  - backend/migrations
scope:
  - deploy/
  - backend/migrations
---

# Database roles are separated

The migrations must use the `migrator` role. The runtime must use the `app` role with DML only.
The audit table must be append-only for the runtime.
