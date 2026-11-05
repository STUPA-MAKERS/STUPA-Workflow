---
id: "000405"
title: A revert needs the right of the original change
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/config_revision
  - backend/app/modules/audit
---

# A revert needs the right of the original change

A revert needs `audit.revert` and the permission of the original change: `form.configure`,
`flow.configure` or `admin.site` for config, `application.transition` for a status change,
`budget.structure` or `budget.book` for budget.
