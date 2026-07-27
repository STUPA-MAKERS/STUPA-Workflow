---
name: be-flow
description: Declarative application state-machine engine: global FlowVersion/State/Transition graph, pure whitelist guard evaluator (NO eval), atomic transition firing with optimistic locking. Also vote-branch firing, auto-advance, deadline scheduling, and notify/webhook/addToNextSession/assignBudget actions. Use when working on transitions, guards, flow actions, vote pass/fail branches, auto/deadline transitions, or status-change audit/revert in backend/app/modules/flow.
---

# Flow / Status Engine — `backend/app/modules/flow`

**Does:** Runs the global declarative state machine that every application moves through. It evaluates guards, fires transitions atomically with audit, deadline and worker actions, and lists the firable transitions for a principal. The admin module stores and edits the graph itself (states and transitions). This module is the runtime engine.

**Key files:**
- `service.py` — `FlowService`: `available_transitions`, `fire`, `auto_advance`, `fire_branch`/`branch_transition`, `available_applicant_transitions`/`fire_as_applicant`, `schedule_state_deadline`, `revert_status`. The CRITICAL core.
- `context.py` — `build_context()`: assembles the pure `GuardContext` from the DB (actor Gremien, applicant roles and Gremien, budget fit, field values and types).
- `dispatch.py` — `DispatchedAction`, `build_dispatched_actions` (worker whitelist filter), `build_implicit_notifications` (auto applicant + task mail), `ActionDispatcher` protocol, `NullActionDispatcher` (log-only default).
- `extras_dispatcher.py` — `FlowExtrasActionDispatcher`: in-process handlers for `addToNextSession` + `assignBudget`. `main.py` wires `build_flow_extras_dispatcher`.
- `router.py` — the 4 application-transition routes. `MANAGE_PERMISSION = "application.transition"`.
- `models.py` — `FlowVersion`, `State`, `Transition` tables.
- `schemas.py` — `TransitionOut`, `TransitionRequest`, `TransitionResult` (camelCase aliases).
- `../../shared/guards.py` — the pure guard evaluator + whitelists + `validate_guard`/`validate_action` (lives in `app/shared`, not in this module).
- `../../shared/config_schemas.py` — `FlowGraph` + `validate_flow_graph` (the graph save-gate and validator).

**Domain / data model:**
- `flow_version` — the ONE global flow (typed flows removed, migration 0019). Partial-unique `uq_flow_version_one_active_global` → exactly one `active` row. Cols: `version` (unique), `active`, `editor_layout` (JSONB).
- `state` — `flow_version_id` (FK CASCADE), `key`, `label_i18n`, `color`, `edit_allowed`, `is_initial`, `is_terminal`, `kind`, `config` (JSONB). `kind ∈ {normal, vote}` (CHECK `state_kind`, approval and decision removed). One partial-unique `is_initial` per flow. Unique `(flow_version_id, key)`. `config.deadlinePolicyKey` materializes a deadline on entry. A `vote` state needs `config.gremiumId`.
- `transition` — `flow_version_id`, `from_state_id`, `to_state_id` (all FK CASCADE), `label_i18n`, `color`, `guard` (JSONB | NULL), `actions` (JSONB list), `order`, `automatic` (the worker fires it when the guard is true), `branch` (`pass`/`fail` for vote-state exits, else NULL), `requires_action` (counts as an open task). The edit lock derives from the target `state.edit_allowed`. `applications.patch` handles it inline and returns 409. It is NOT a dispatched action.
- A fired transition writes a `StatusEvent` (in `applications.models`) + a `status_change` audit entry in the same transaction.

**Guard catalog (`shared/guards.py`):** declarative, whitelist, NO eval. `eval_guard(guard, ctx)` takes a single-key dict. An empty guard or None gives True.
- Combinators: `and`, `or`, `not`.
- Conditions (auto + manual): `deadlinePassed`, `applicantRoleIs`, `applicantCommitteeIs`, `budgetIs`, `budgetFitsApplication`, `hasField`, `compare` ({field, op, value}, typed by the field type of the pinned form version, fail-closed on a missing field or an unknown op).
- Actor gates (MANUAL only, rejected on automatic transitions by `allow_actor_ops=False`): `roleIs`, `isInCommittee`, `actorIsApplicant`.
- Action whitelist: `webhook` (needs `webhookId`), `notify` (needs `recipients[]` of kind gremium/role/applicant/email), `addToNextSession` (needs `gremiumId`, only on a transition INTO a vote state), `assignBudget` (needs `budgetId`). An unknown operator or action raises `GuardError` at SAVE time (`validate_guard`/`validate_action`/`validate_flow_graph`), not at runtime.

**API surface:**
- `GET  /api/applications/{id}/transitions` — P(`application.transition`). The firable manual transitions. The engine evaluates the guards for the principal and excludes `automatic` and `branch`.
- `POST /api/applications/{id}/transition` — P(`application.transition`). Fire a transition → 200 `{newStateId, statusEventId, dispatchedActions}` or 409 on a guard, a state conflict or a race.
- `GET  /api/applications/{id}/applicant-transitions` — magic-link applicant. Only manual transitions gated by `actorIsApplicant`.
- `POST /api/applications/{id}/applicant-transition` — fire as applicant (403 unless `actorIsApplicant` opened it).
- Flow GRAPH CRUD is NOT here. It lives in the admin module: `GET/POST /api/flow-versions/global` (`AdminService.get_active_global_flow`/`create_global_flow_version`), validated by `validate_flow_graph`.

**Conventions & gotchas:**
- `fire()` uses optimistic locking. The rowcount of `UPDATE … WHERE current_state_id = from_state_id` must be 1, else the call gives 409 for a concurrent transition. Always re-check the state, never assume it.
- Only the vote outcome fires a branch transition (`pass`/`fail`), through `fire_branch` with `manual=False`. A manual `fire` of a branch transition gives 409, because nobody may set a vote result by hand. `voting.service` calls `fire_branch` on close.
- `auto_advance` NEVER fires out of a `vote` state. This is fail-closed, and the validator also forbids an automatic non-branch exit from a vote state. Otherwise the engine would approve an application without a vote.
- The engine fills the actor roles and Gremien only for a `manual=True` context. An automatic run sees empty actor sets, so an actor gate cannot pass.
- Worker actions dispatch AFTER the commit. They are idempotent and retryable and carry a stable `idempotency_key`. The engine logs an action failure and swallows it. An action must never roll back the committed state change. `build_dispatched_actions` filters again to the worker whitelist (`notify`, `webhook`, `addToNextSession`, `assignBudget`). It skips `setEditLock` and the rest.
- Every fire emits implicit mails: a `notify` to the applicant and a `taskNotify` to the actors of the new state. An explicit applicant `notify` in the config replaces the implicit one.
- Deadlines: on entry into a state, `schedule_state_deadline` deletes the `flow_deadline` rows of the state you leave. If `config.deadlinePolicyKey` resolves, it creates a new row. That row pins the `order`-first transition whose guard fires on the elapsed deadline alone (`_DEADLINE_ONLY_CTX`). The T-44 cron fires it. On a manual path the engine reads `deadlinePassed` from the DB.
- `revert_status` (audit-log revert) flips the state back ONLY while the application still sits in `to_state_id`, else 409 `stale_revert`. It re-materializes the deadline. It does NOT undo side effects such as canceled votes or sent webhooks and mails. `config_revision.revert` calls it.
- Strongly-typed Python ≥3.13 ([[python-strong-typing]]). All errors are `ProblemDetail` (RFC-9457). See the `conventions` skill. Revert scope: [[revert-feature-scope]]. Flow redesign spec: [[flow-engine-redesign]]. Prior fixes: [[flow-engine-bug-fixes]].

**Related:** be-admin, be-applications, be-voting, be-deadlines, be-budget, be-audit, be-config-revision
