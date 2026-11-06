---
id: "000266"
title: Every user holds the member role
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/auth
  - backend/app/deps.py
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# Every user holds the member role

Every principal must hold the role `member`. A global role must come only from `group_mapping`
and from the bootstrap.
