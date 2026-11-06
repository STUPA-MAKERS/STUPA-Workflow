---
id: "000158"
title: Role assignments can be revoked without a login
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/admin/principal_revoke.py
  - backend/app/modules/admin/router.py
  - frontend/src/app/pages/admin/users/user-revoke
scope:
  - backend/app/modules/auth
  - backend/app/modules/admin
---

# Role assignments can be revoked without a login

A person can leave an SSO group and not log in again. A holder of `admin.users.revoke_groups`
must then be able to remove the roles and memberships of that person.
