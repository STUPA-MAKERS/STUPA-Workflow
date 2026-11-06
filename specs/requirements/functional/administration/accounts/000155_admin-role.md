---
id: "000155"
title: The admin role has every permission
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/auth
  - backend/app/modules/admin
scope:
  - backend/app/modules/auth
  - backend/app/modules/admin
---

# The admin role has every permission

The role `admin` must have every permission, and an admin must not be able to edit it. The
roles `admin` and `member` must not be deletable.
