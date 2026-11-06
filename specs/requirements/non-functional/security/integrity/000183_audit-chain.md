---
id: "000183"
title: The audit log is append-only
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/audit/service.py
  - backend/app/modules/audit/models.py
scope:
  - backend/app/modules/audit
---

# The audit log is append-only

An audit entry must not change and must not be deleted. Each entry holds the sha256 hash of
the entry before it. A database trigger refuses an update or a delete.
