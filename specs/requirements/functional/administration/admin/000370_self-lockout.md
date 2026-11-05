---
id: "000370"
title: An admin cannot deactivate the own account
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
  - backend/app/modules/auth
---

# An admin cannot deactivate the own account

An admin cannot deactivate the own account. Break-glass access comes from
`BOOTSTRAP_ADMIN_SUBJECTS`, `BOOTSTRAP_ADMIN_EMAILS` or `admin-cli`.
