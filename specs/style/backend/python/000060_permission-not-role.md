---
id: "000060"
title: A gate names a permission, not a role
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
---

# A gate names a permission, not a role

Gate an action on a permission key. Do not compare with the role name `"admin"`. A destructive
action that needs its own key gets one, and a migration grants it to the admin role.

Reason: A role check cannot be delegated.
