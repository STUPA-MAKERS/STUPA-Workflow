---
name: crud-completeness-rules
description: Every entity gets full CRUD behind a permission. Five entities stay immutable on purpose, and four deletes are conditional
metadata:
  node_type: memory
  type: project
---

Rule the user set: **every domain entity supports Create, Read, Update and Delete for an admin
or for the holder of the right permission.** A missing route is a bug unless it appears on the
list below.

## The immutable five — do NOT "fix" these

Each one carries the reason in its own model docstring, so an audit does not raise it again.

- **`AuditEntry`** — append-only sha256 hash chain. A database trigger rejects UPDATE, DELETE
  and TRUNCATE. `POST /admin/audit/{id}/revert` reverses the EFFECT, never the entry.
- **`ConfigRevision`** — append-only snapshot chain, same kind of trigger. Restore, never
  delete.
- **`Ballot` / `SecretBallot`** — a cast vote records a decision. An edit would rewrite the
  result after the fact. `cancel` on the vote voids a whole round.
- **`FormVersion` / `FlowVersion`** — an application points at the version it was filled in
  under. An editor saves a NEW version. Roll back through a config-revision restore.
- **`ErasureRequest`** — the GDPR queue row is the proof that a request was handled. The
  foreign keys use `ON DELETE SET NULL`, so the row outlives the subject.

## Deletes that exist but stay conditional

- A **protocol** deletes only while it is a `draft`. A `final` protocol is a signed record, and
  a `rendering` one is frozen while the worker builds the PDF.
- A **vote** deletes only while it is `draft` or `cancelled`. An open or closed vote is part of
  the meeting record (`vote_not_deletable`).
- A **fiscal year** does not delete while bookings or allocations reference it.
- A **CD variant** does not delete while a Gremium still uses it.

Each of these answers **409**, never a silent cascade.

## Permission, not role

Gate a destructive action on a permission key, never on the literal role string `"admin"`,
because a role check cannot be delegated. If a destructive action needs its own key, split it
out the way `application.delete`, `admin.types_delete` and `application.force_status` are,
and grant it to the admin role in a migration so nothing changes for an installed system.
See [[admin-domain-rules]].
