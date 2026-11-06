---
id: "000370"
title: An admin cannot deactivate the own account
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/admin/principal_revoke.py
  - backend/app/modules/auth/bootstrap.py
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
  - backend/app/modules/auth
---

# An admin cannot deactivate the own account

An admin must not be able to deactivate the own account. Break-glass access must come only from
`BOOTSTRAP_ADMIN_SUBJECTS`, `BOOTSTRAP_ADMIN_EMAILS` or `admin-cli`.
