---
name: revert-feature-scope
description: Audit-log revert covers config, status transitions and budget/bookings. Deletes and assign/move stay out on purpose. Design rules and permissions
metadata:
  node_type: memory
  type: project
---

The rules are specs in `specs/` of the STUPA-Workflow repository. Read the spec, not this
file:

- `F/administration/admin/000163` The audit revert reverses effects, never entries
- `F/administration/admin/000405` A revert needs the right of the original change
- `F/applications/flow/000242` A status revert works only from the reverted state
- `F/finance/budget/000255` Every money change is audited and revertable
- `F/finance/budget/000145` A reverted booking keeps the invoice status
- `F/administration/admin/000383` A config revert goes forward
