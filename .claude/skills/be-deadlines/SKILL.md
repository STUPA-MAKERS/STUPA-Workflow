---
name: be-deadlines
description: Named deadline policies that the flow engine references (DeadlinePolicy registry, key/absolute/relative_submitted/relative_changed). The arq cron scans the Deadline table to fire deadlinePassed transitions, send deadline_approaching reminders and auto-close votes. Use when working on deadlines, deadline policies, /admin/deadline-policies, due_at/action_on_pass, or the deadline cron worker in backend/app/modules/deadlines.
---

# Deadlines & deadline policies — `backend/app/modules/deadlines`

**Does:** Stores per-application and per-type deadlines (`Deadline`). It also holds an admin-curated registry of named, reusable deadline policies (`DeadlinePolicy`). The flow engine references a policy by `key`. An arq cron worker scans the due rows to fire flow transitions, send reminders and auto-close votes.

**Key files:**
- `models.py` — `Deadline` (timepoint bound to an application or a type, optional expiry action) and `DeadlinePolicy` (named registry: absolute or relative due-at) ORM models + partial scan indexes + kind CheckConstraint.
- `service.py` — `DeadlineService` (scan/lock/marker DB layer for the cron), `DeadlinePolicyService` (policy CRUD), pure `resolve_due_at(policy, …)`, `transition_ref(action_on_pass)`, `DeadlinePolicyError`.
- `schemas.py` — `DeadlinePolicyCreate/Update/Out` (camelCase aliases), `DeadlineKind` literal, `I18nMap` label.
- `router.py` — admin CRUD router for the policy registry (`/admin/deadline-policies`).
- `../../../worker/deadlines.py` — the arq cron (`process_deadlines`) that consumes `DeadlineService`. The business effects live HERE, not in the module service.

**Domain / data model:**
- **`deadline`** — `application_id` (FK→application, CASCADE, NULL for type-only template deadlines), `type_id` (FK→application_type, CASCADE), `kind` (free-text classification such as `flow_phase`, `vote` or `requeue`, for information and filtering only), `due_at` (timestamptz), `action_on_pass` (JSONB, NULL = plain reminder or display deadline, `{"transitionId": "<uuid>"}` = the transition to fire on expiry), `reminded_at` (timestamptz, NULL = not yet reminded). Two **partial** indexes: `ix_deadline_due_at_action` (`WHERE action_on_pass IS NOT NULL`) and `ix_deadline_reminder` (`WHERE reminded_at IS NULL`).
- **`deadline_policy`** — `key` (Text, UNIQUE, the stable reference the flow uses, immutable on update), `label` (JSONB I18nMap), `kind`, `absolute_at` (timestamptz, only for `absolute`), `offset_days` (int, only for the relative variants), `created_at`/`updated_at`. CheckConstraint `deadline_policy_kind`: kind ∈ `absolute`, `relative_submitted`, `relative_changed`.
- **Policy kinds** decouple the concrete date from the flow definition. A date can then change, for example per semester, without a new flow version. `absolute` → fixed `absolute_at`. `relative_submitted` → `application.created_at` + `offset_days`. `relative_changed` → `application.updated_at` + `offset_days`. `resolve_due_at` returns `None` when the needed reference timestamp is missing.

**API surface:** (full prefix `/api/admin/deadline-policies`)
- `GET /api/admin/deadline-policies` — list the policies, ordered by key. A reader needs `admin.deadlines` OR `flow.configure`, because the flow editor offers them as guard and action choices.
- `POST /api/admin/deadline-policies` — create. A duplicate key gives 409 (`deadline_policy_key`). Needs `admin.deadlines`.
- `PATCH /api/admin/deadline-policies/{policy_id}` — partial update. The key stays unchangeable. The service blanks the value field that does not match the kind. Needs `admin.deadlines`.
- `DELETE /api/admin/deadline-policies/{policy_id}` — 204. Needs `admin.deadlines`.

**Conventions & gotchas:**
- **No HTTP endpoint creates `Deadline` rows.** `DeadlineService.create` is a programmatic API. The router manages only the *policy* registry.
- **Idempotency markers:** after a fire, the cron sets `action_on_pass=NULL` (`consume_action`). The row then leaves the partial action index and never fires twice. `reminded_at` gives exactly-once reminders.
- **Concurrency:** every `lock_*` method selects a single row with `FOR UPDATE SKIP LOCKED`. A second worker skips a held deadline, so nothing runs twice. `_fire_one` sets the marker *before* `flow.fire`, which commits it atomically with the state change.
- **Cron flow:** `worker/deadlines.py:process_deadlines` runs every minute. It sends the reminders first. Then it runs the expiry actions with `flow.fire` (`deadlinePassed=True`, `manual=False`). A `kind="requeue"` deadline returns the application through the referenced transition. Next come the configured `automatic` transitions and the vote auto-close (`voting.close`). Last it discards unconfirmed guest applications (12h TTL). It uses a `system:deadlines` principal with `application.manage`.
- **The `absolute` and `relative` value fields exclude each other.** Create and update null out the field that does not match `kind`. Read `resolve_due_at` or the service instead of both fields.
- `transition_ref` is defensive. It accepts `transitionId` or `transition_id`. It returns `None` for a missing or invalid UUID, and the caller then skips the deadline.
- The `deadlinePassed` guard lives in the flow module (`be-flow`). `deadline_approaching` is a notification template (`be-notifications`). For the guard catalog and the vote context, see `[[flow-engine-redesign]]` and `[[sessions-protokollant-redesign]]`.

**Related:** be-flow, be-voting, be-notifications, be-applications
