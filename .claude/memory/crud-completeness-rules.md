---
name: crud-completeness-rules
description: Every entity gets full CRUD behind a permission. Five entities stay immutable on purpose, and four deletes are conditional
metadata:
  node_type: memory
  type: project
---

The rules are specs in `specs/` of the STUPA-Workflow repository. Read the spec, not this
file:

- `F/administration/admin/000161` Every entity has create, read, update and delete
- `S/backend/database/000072` Five record types are immutable
- `F/meetings/voting/000029` A vote can be deleted only as draft or cancelled
- `F/meetings/protocols/000117` Only a draft protocol is deleted
- `F/finance/budget/000141` A fiscal year in use is not deleted
- `F/administration/admin/000162` A CD variant in use is not deleted
- `S/backend/python/000060` A gate names a permission, not a role
