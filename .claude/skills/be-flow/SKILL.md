---
name: be-flow
description: Declarative application state-machine engine — global FlowVersion/State/Transition graph, pure whitelist guard evaluator (NO eval), atomic transition firing with optimistic locking, vote-branch firing, auto-advance, deadline scheduling, and notify/webhook/addToNextSession/assignBudget actions. Use when working on transitions, guards, flow actions, vote pass/fail branches, auto/deadline transitions, or status-change audit/revert in backend/app/modules/flow.
---

# Flow / Status Engine — `backend/app/modules/flow`

**Does:** Runs the global declarative state machine that every application moves through: evaluates guards, fires transitions atomically (with audit + deadline + worker actions), and exposes the firable transitions for a principal. The graph itself (states/transitions) is stored/CRUD'd by the admin module; this module is the runtime engine.

**Key files:**
- `service.py` — `FlowService`: `available_transitions`, `fire`, `auto_advance`, `fire_branch`/`branch_transition`, `available_applicant_transitions`/`fire_as_applicant`, `schedule_state_deadline`, `revert_status`. The CRITICAL core.
- `context.py` — `build_context()`: assembles the pure `GuardContext` from DB (actor committees, applicant roles/committees, budget fit, field values/types).
- `dispatch.py` — `DispatchedAction`, `build_dispatched_actions` (worker whitelist filter), `build_implicit_notifications` (auto applicant + task mail), `ActionDispatcher` protocol, `NullActionDispatcher` (log-only default).
- `extras_dispatcher.py` — `FlowExtrasActionDispatcher`: in-process handlers for `addToNextSession` + `assignBudget`; `build_flow_extras_dispatcher` wired in `main.py`.
- `router.py` — the 4 application-transition routes; `MANAGE_PERMISSION = "application.transition"`.
- `models.py` — `FlowVersion`, `State`, `Transition` tables.
- `schemas.py` — `TransitionOut`, `TransitionRequest`, `TransitionResult` (camelCase aliases).
- `../../shared/guards.py` — the pure guard evaluator + whitelists + `validate_guard`/`validate_action` (lives in `app/shared`, not this module).
- `../../shared/config_schemas.py` — `FlowGraph` + `validate_flow_graph` (the graph save-gate / validator).

**Domain / data model:**
- `flow_version` — the ONE global flow (typed flows removed, migration 0019). Partial-unique `uq_flow_version_one_active_global` → exactly one `active` row. Cols: `version` (unique), `active`, `editor_layout` (JSONB).
- `state` — `flow_version_id` (FK CASCADE), `key`, `label_i18n`, `color`, `edit_allowed`, `is_initial`, `is_terminal`, `kind`, `config` (JSONB). `kind ∈ {normal, vote}` (CHECK `state_kind`; approval/decision removed). Partial-unique one `is_initial` per flow; unique `(flow_version_id, key)`. `config.deadlinePolicyKey` materializes a deadline on entry; `vote` states need `config.gremiumId`.
- `transition` — `flow_version_id`, `from_state_id`, `to_state_id` (all FK CASCADE), `label_i18n`, `color`, `guard` (JSONB | NULL), `actions` (JSONB list), `order`, `automatic` (worker fires when guard true), `branch` (`pass`/`fail` for vote-state exits, else NULL), `requires_action` (counts as open task). Edit-lock derives from target `state.edit_allowed` (handled inline in `applications.patch`, 409 — NOT a dispatched action).
- A fired transition writes a `StatusEvent` (in `applications.models`) + a `status_change` audit entry in the same transaction.

**Guard catalog (`shared/guards.py`):** declarative, whitelist, NO eval. `eval_guard(guard, ctx)` — single-key dict; empty/None ⇒ True.
- Combinators: `and`, `or`, `not`.
- Conditions (auto + manual): `deadlinePassed`, `applicantRoleIs`, `applicantCommitteeIs`, `budgetIs`, `budgetFitsApplication`, `hasField`, `compare` ({field, op, value}, typed by the pinned form-version field type; fail-closed on missing field / unknown op).
- Actor gates (MANUAL only; rejected on automatic transitions via `allow_actor_ops=False`): `roleIs`, `isInCommittee`, `actorIsApplicant`.
- Action whitelist: `webhook` (needs `webhookId`), `notify` (needs `recipients[]` of kind gremium/role/applicant/email), `addToNextSession` (needs `gremiumId`, only on a transition INTO a vote state), `assignBudget` (needs `budgetId`). Unknown operator/action ⇒ `GuardError` at SAVE time (`validate_guard`/`validate_action`/`validate_flow_graph`), not at runtime.

**API surface:**
- `GET  /api/applications/{id}/transitions` — P(`application.transition`); firable manual transitions (guards evaluated for principal; excludes `automatic` and `branch`).
- `POST /api/applications/{id}/transition` — P(`application.transition`); fire a transition → 200 `{newStateId, statusEventId, dispatchedActions}` or 409 (guard/state conflict/race).
- `GET  /api/applications/{id}/applicant-transitions` — magic-link applicant; only `actorIsApplicant`-gated manual transitions.
- `POST /api/applications/{id}/applicant-transition` — fire as applicant (403 unless `actorIsApplicant`-opened).
- Flow GRAPH CRUD is NOT here — it's in the admin module: `GET/POST /api/flow-versions/global` (`AdminService.get_active_global_flow`/`create_global_flow_version`), validated by `validate_flow_graph`.

**Conventions & gotchas:**
- `fire()` uses optimistic locking: the `UPDATE … WHERE current_state_id = from_state_id` rowcount must be 1 else 409 (concurrent transition). Always re-check state, never assume.
- Branch transitions (`pass`/`fail`) are fired ONLY by the vote outcome via `fire_branch` (`manual=False`); a manual `fire` of a branch transition is a 409 — vote results cannot be set by hand. `voting.service` calls `fire_branch` on close.
- `auto_advance` NEVER fires out of a `vote` state (fail-closed; the validator also forbids automatic non-branch exits from vote states) — otherwise an application would be "auto-approved" without a vote.
- Actor roles/committees are only populated for `manual=True` contexts; automatic runs see empty actor sets, so actor gates can't pass.
- Worker actions dispatch AFTER commit (idempotent, retryable, stable `idempotency_key`). Action failures are logged and swallowed — they must never roll back the committed state change. `build_dispatched_actions` re-filters to the worker whitelist (`notify`, `webhook`, `addToNextSession`, `assignBudget`); `setEditLock` and others are skipped.
- Every fire emits implicit mails: a `notify` to the applicant (unless an explicit applicant `notify` is configured) + a `taskNotify` to the new state's actors.
- Deadlines: on entering a state, `schedule_state_deadline` deletes the leaving state's `flow_deadline`(s) and, if `config.deadlinePolicyKey` resolves, creates a new one pinned to the `order`-first transition whose guard fires on the elapsed deadline alone (`_DEADLINE_ONLY_CTX`); the T-44 cron fires it. `deadlinePassed` on manual paths is read from the DB.
- `revert_status` (audit-log revert) flips state back ONLY if still in `to_state_id` (else 409 `stale_revert`); it re-materializes the deadline but does NOT undo side effects (cancelled votes, sent webhooks/mails). Called from `config_revision.revert`.
- Strongly-typed Python ≥3.13 ([[python-strong-typing]]); all errors are `ProblemDetail` (RFC-9457). See the `conventions` skill. Revert scope: [[revert-feature-scope]]; flow redesign spec: [[flow-engine-redesign]]; prior fixes: [[flow-engine-bug-fixes]].

**Related:** be-admin, be-applications, be-voting, be-deadlines, be-budget, be-audit, be-config-revision
