---
id: "000274"
title: Tokens can be revoked
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# Tokens can be revoked

A user can list and revoke their own grants. A holder of `admin.users` can revoke the grant
of any person. Both use the same revocation path.
