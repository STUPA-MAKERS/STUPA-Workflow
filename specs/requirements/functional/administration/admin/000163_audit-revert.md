---
id: "000163"
title: The audit revert reverses effects, never entries
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/config_revision/revert.py
  - backend/app/modules/audit_log/router.py
  - frontend/src/app/pages/admin/audit/audit-log.component.ts
scope:
  - backend/app/modules/config_revision
  - backend/app/modules/audit
  - frontend/src/app/pages/admin/audit
---

# The audit revert reverses effects, never entries

"Zurücknehmen" must reverse the effect of a config change, a status change or a budget change.
It must never delete or change an audit entry. 000383 (config), 000242 (status) and 000255
(budget) give the conditions of each kind.
