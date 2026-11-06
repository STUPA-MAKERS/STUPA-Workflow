---
id: "000274"
title: Tokens can be revoked
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# Tokens can be revoked

A user must be able to list and revoke their own grants. A holder of `admin.users` must be able
to revoke the grant of any person. Both must use the same revocation path.
