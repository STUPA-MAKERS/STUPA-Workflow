---
name: crud-completeness-rules
description: Every entity gets full CRUD behind a permission. Five entities stay immutable on purpose
metadata:
  node_type: memory
  type: project
---

Rule the user set (2026-08-06): **every domain entity supports Create, Read, Update and
Delete for an admin or for the holder of the right permission.** A missing route is a bug
unless it appears on the list below.

## The immutable five — do NOT "fix" these

Each one carries the reason in its own model docstring, so an audit does not raise it again.

- **`AuditEntry`** — append-only sha256 hash chain. A database trigger rejects UPDATE and
  DELETE. `POST /admin/audit/{id}/revert` reverses the EFFECT, never the entry.
- **`ConfigRevision`** — append-only snapshot chain, same trigger. Restore, never delete.
- **`Ballot` / `SecretBallot`** — a cast vote records a decision. An edit would rewrite the
  result after the fact. `cancel` on the vote voids a whole round.
- **`FormVersion` / `FlowVersion`** — an application points at the version it was filled in
  under. An editor saves a NEW version. Roll back through a config-revision restore.
- **`ErasureRequest`** — the GDPR queue row is the proof that a request was handled. The
  foreign keys use `ON DELETE SET NULL` so the row outlives the subject.

## Deletes that exist but stay conditional

- A **protocol** deletes only while it is a draft. A finalized protocol is a signed record.
- A **vote** deletes only while it was never opened and holds no ballot.
- A **fiscal year** does not delete while bookings or allocations hang on it.
- A **CD variant** does not delete while a Gremium still uses it.

Each of these answers **409**, never a silent cascade.

## Permission, not role

`DELETE /api/applications/{id}` used to test the literal role string `"admin"`, which made
the capability impossible to delegate. Gate on a permission key. If a destructive action
needs its own key, split it out the way `admin.types_delete` and `application.force_status`
already do, and grant it to the admin role in a migration so nothing changes for an
installed system. See [[admin-domain-rules]].
