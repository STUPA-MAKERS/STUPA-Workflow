---
id: "000158"
title: Role assignments can be revoked without a login
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/modules/admin
---

# Role assignments can be revoked without a login

A person can leave an SSO group and not log in again. A holder of `admin.users.revoke_groups`
can then remove the roles and memberships of that person.
