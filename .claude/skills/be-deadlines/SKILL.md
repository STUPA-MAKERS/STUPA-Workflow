---
name: be-deadlines
description: Named deadline policies (DeadlinePolicy registry, key/absolute/relative_submitted/relative_changed) referenced by the flow engine, plus the Deadline table the arq cron scans to fire deadlinePassed transitions, send deadline_approaching reminders and auto-close votes. Use when working on deadlines, deadline policies, /admin/deadline-policies, due_at/action_on_pass, or the deadline cron worker in backend/app/modules/deadlines.
---

# Deadlines & deadline policies — `backend/app/modules/deadlines`

**Does:** Stores per-application/per-type deadlines (`Deadline`) and an admin-curated registry of named, reusable deadline policies (`DeadlinePolicy`) that the flow engine references by `key`. An arq cron worker scans due rows to fire flow transitions, send reminders, and auto-close votes.

**Key files:**
- `models.py` — `Deadline` (timepoint bound to an application/type, optional expiry action) and `DeadlinePolicy` (named registry: absolute or relative due-at) ORM models + partial scan indexes + kind CheckConstraint.
- `service.py` — `DeadlineService` (scan/lock/marker DB layer for the cron), `DeadlinePolicyService` (policy CRUD), pure `resolve_due_at(policy, …)`, `transition_ref(action_on_pass)`, `DeadlinePolicyError`.
- `schemas.py` — `DeadlinePolicyCreate/Update/Out` (camelCase aliases), `DeadlineKind` literal, `I18nMap` label.
- `router.py` — admin CRUD router for the policy registry (`/admin/deadline-policies`).
- `../../../worker/deadlines.py` — the arq cron (`process_deadlines`) that consumes `DeadlineService`; the business effects live HERE, not in the module service.

**Domain / data model:**
- **`deadline`** — `application_id` (FK→application, CASCADE, NULL for type-only template deadlines), `type_id` (FK→application_type, CASCADE), `kind` (free-text classification e.g. `flow_phase`, `vote`, `requeue`; informational/filterable only), `due_at` (timestamptz), `action_on_pass` (JSONB, NULL=plain reminder/display deadline; `{"transitionId": "<uuid>"}` = transition ref to fire on expiry), `reminded_at` (timestamptz, NULL=not yet reminded). Two **partial** indexes: `ix_deadline_due_at_action` (`WHERE action_on_pass IS NOT NULL`) and `ix_deadline_reminder` (`WHERE reminded_at IS NULL`).
- **`deadline_policy`** — `key` (Text, UNIQUE; the stable reference the flow uses; immutable on update), `label` (JSONB I18nMap), `kind`, `absolute_at` (timestamptz, only for `absolute`), `offset_days` (int, only for relative variants), `created_at`/`updated_at`. CheckConstraint `deadline_policy_kind`: kind ∈ `absolute`, `relative_submitted`, `relative_changed`.
- **Policy kinds** decouple the concrete date from the flow definition so a date can change (e.g. per semester) without re-versioning the flow: `absolute` → fixed `absolute_at`; `relative_submitted` → `application.created_at` + `offset_days`; `relative_changed` → `application.updated_at` + `offset_days`. `resolve_due_at` returns `None` when the needed reference timestamp is missing.

**API surface:** (full prefix `/api/admin/deadline-policies`)
- `GET /api/admin/deadline-policies` — list policies (ordered by key); readable with `admin.deadlines` OR `flow.configure` (flow editor needs them as guard/action choices).
- `POST /api/admin/deadline-policies` — create; 409 (`deadline_policy_key`) on duplicate key. `admin.deadlines`.
- `PATCH /api/admin/deadline-policies/{policy_id}` — partial update (key is unchangeable); the service blanks the off-kind value field. `admin.deadlines`.
- `DELETE /api/admin/deadline-policies/{policy_id}` — 204. `admin.deadlines`.

**Conventions & gotchas:**
- **No HTTP endpoint creates `Deadline` rows** — `DeadlineService.create` is a programmatic API; the router only manages the *policy* registry.
- **Idempotency markers:** after firing, the cron sets `action_on_pass=NULL` (`consume_action`) so the row leaves the partial action index and never fires twice; `reminded_at` gives exactly-once reminders.
- **Concurrency:** all `lock_*` methods select a single row with `FOR UPDATE SKIP LOCKED` so a second worker skips a held deadline — no double execution. In `_fire_one` the marker is set *before* `flow.fire`, which commits it atomically with the state change.
- **Cron flow:** `worker/deadlines.py:process_deadlines` runs per-minute and does reminders → expiry actions (`flow.fire` with `deadlinePassed=True`, `manual=False`; `kind="requeue"` is the Wiedervorlage case) → configured `automatic` transitions → vote auto-close (`voting.close`) → discard unconfirmed guest applications (12h TTL). It uses a `system:deadlines` principal with `application.manage`.
- **`absolute`/`relative` value fields are mutually exclusive** — create/update null out the non-applicable one based on `kind`; trust `resolve_due_at`/the service rather than reading both.
- `transition_ref` is defensive: it accepts `transitionId` or `transition_id` and returns `None` on missing/invalid UUID (caller skips the deadline).
- The `deadlinePassed` guard lives in the flow module (`be-flow`); `deadline_approaching` is a notification template (`be-notifications`). See `[[flow-engine-redesign]]` and `[[sessions-protokollant-redesign]]` for guard-catalogue/vote context.

**Related:** be-flow, be-voting, be-notifications, be-applications
