---
id: "000470"
title: The audit read is global
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/audit
---

# The audit read is global

`audit.read` must be granted only to a global role.

Reason: The permission has no Gremium scope and shows every entry.
