---
id: "000163"
title: The audit revert reverses effects, never entries
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/config_revision
  - backend/app/modules/audit
  - frontend/src/app/pages/admin/audit
---

# The audit revert reverses effects, never entries

"Zurücknehmen" reverses the effect of a config change, a status change or a budget change.
A delete is not revertable. A status revert works only while the Antrag is still in the
target state. A stale revert answers 409.
