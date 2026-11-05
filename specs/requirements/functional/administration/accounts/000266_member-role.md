---
id: "000266"
title: Every user holds the member role
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# Every user holds the member role

Every principal holds the role `member`. Global roles
come only from `group_mapping` and from the bootstrap.
