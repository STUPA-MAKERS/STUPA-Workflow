---
id: "000060"
title: A gate names a permission, not a role
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/
---

# A gate names a permission, not a role

A gate must name a permission key, never the role name `"admin"`. A destructive action that
needs its own key must get one, and a migration must grant it to the admin role.

Reason: A role check cannot be delegated.
