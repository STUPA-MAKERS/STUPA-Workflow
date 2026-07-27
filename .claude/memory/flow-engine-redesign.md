---
name: flow-engine-redesign
description: "Canonical design of the redesigned flow engine — state kinds, guard catalog, actions, permissions, manual-transition UI. The user confirmed every decision with the question tool."
metadata: 
  node_type: memory
  type: project
---

Flow-engine redesign, branch feat/admin-ux-flow-editor-fixes (2026-06-09, DONE, 7 commits pushed). The user confirmed every decision below with the question tool. Nothing here is an assumption. This is the authoritative design record.

## State kinds
- Keep `normal` + `vote` ONLY. Dropped `approval` + `decision`. Both were redundant: approval is a manual `roleIs` transition, decision is an automatic guard transition. Model CheckConstraint `kind IN ('normal','vote')`. Migration 0038 moves existing approval/decision rows over to normal.
- `vote`: a Gremium votes. `config.gremiumId` required, exactly 2 outgoing transitions with `branch` `pass`/`fail`. Vote close (voting/service) fires the branch via `flow.fire_branch(branch_name)`: passed→pass, rejected/tie→fail (tie is fail-closed). `vote.result_branch_transition_id` records the fired branch.

## Transitions
- `automatic` flag (fires by itself when the guard holds, worker/cron, manual=False) vs manual (the user fires it from the detail view). NO separate actor field. Guards gate the actor.
- `branch` (pass/fail) only on vote-state outgoings.

## Guard catalog (shared/guards.py, mirrored in guard-builder.util.ts)
Single-operator dicts, whitelist, no eval. Leaf ops:
- **Conditions (auto + manual):** `deadlinePassed`(bool), `applicantRoleIs`(global role key), `applicantCommitteeIs`(gremium id — ANY active membership), `budgetIs`(assigned cost center = application.budget_id), `budgetFitsApplication`(bool: amount ≤ allocation − Σ direct BudgetExpense of the assigned node+fiscal-year), `hasField`(field key present/non-empty), `compare`.
- **Actor gates (MANUAL only):** `roleIs`(actor global role), `isInCommittee`(actor gremium id — ANY active membership). `validate_guard(allow_actor_ops=not t.automatic)` rejects these on automatic transitions.
- Combinators: `and`/`or`/`not`.
- REMOVED: `permissionIs`, `voteResult` (→ vote branches), `manual` (→ automatic flag), `fieldsComplete` (→ hasField/fieldValueIs). The patch and submit endpoints still check submit-completeness.

### `compare` guard — typed, over ANY form field by key
`{"compare":{"field":"<key>","op":"<op>","value":<v>}}`. `field` = any form-field key OR built-in `amount`(currency). The engine reads the value type at runtime from the field def (number/currency→numeric, date→date, checkbox→bool, else text). Op set by type: numeric, currency and date take `== != < <= > >=`. Text and select take `== != in` (in→list). Bool takes `==`. A wrong op for the type raises an error. This replaced the earlier valueLargerThan/SmallerThan + fieldValueIs ideas (user: "use generic promoted values, manage differing types"). The editor offers all COMPARE_OPS + a free-text value, because the field type is unknown at edit time for a global flow.

### Guard context (flow/context.py, async, loads from DB)
The context carries:
- manual flag
- actor roles + actor_committees (only when manual)
- applicant_roles (data['_applicantRoles']) + applicant_committees (created_by sub memberships)
- budget_id
- budget_fits
- field_values (data + amount) + field_types map

## Actions (3 kept + 1 added, implemented properly — not stubs)
ACTION_TYPES = `{webhook, notify, addToNextSession, assignBudget}`. Dropped exportPdf/setEditLock/budgetReserve/budgetBook/openVote/requeue. Dispatch chain in main.py: notify-dispatcher + webhook-dispatcher + FlowExtrasActionDispatcher (addToNextSession+assignBudget). Post-commit, idempotent via DispatchedAction.idempotency_key `app:statusEvent:index:type`.
- **webhook**: `{webhookId}` references an existing admin/webhooks entry (NOT inline url, NOT event-fanout). `WebhookService.dispatch_to_webhook` creates one delivery for that hook, event `application.transition`, payload {applicationId,transitionId,statusEventId}, dedup on (webhook_id, idempotency_key).
- **notify**: `{recipients:[{kind,ref?}]}`. Kinds: `gremium`(all current members' emails), `role`(global role holders), `applicant`, `email`(literal). RecipientResolver now also handles gremium + email. The action reuses `NotificationService.handle_notify_action`, which needs a templateKey to send a real mail.
- **addToNextSession**: `{gremiumId}`. ONLY valid on a transition whose target state kind==vote (validated in the flow graph). Dispatch → earliest FUTURE Meeting of the gremium (date ≥ today, not finalized) → AgendaService.add. No upcoming meeting → log a warning + no-op (skip, do NOT auto-create).
- **assignBudget**: `{budgetId}`. The action sets application.budget_id to the cost center. It derives fiscal_year from the single active fiscal year of the top-level node. If there is no single active fiscal year, it leaves the field open.

## Permissions — reworked to 16 keys (shared/permissions.py)
The keys: application.read, application.create, application.transition, application.manage, form.configure, flow.configure, vote.cast, vote.manage, meeting.manage, budget.view, budget.manage, notification.manage, webhook.manage, audit.read, admin.config, admin.roles.
`application.transition` gates manual firing. The flow router uses it, and it replaced application.manage there. DROPPED: application.update(→manage), protocol.manage + protocol.write(→meeting.manage). The protocol router now gates on meeting.manage. Migration 0039 carries over grants (manage→transition, protocol.write→meeting.manage) + deletes the dropped keys.

## Manual-transition UI (application detail)
GET /applications/{id}/transitions (guard-filtered, manual-only) + POST .../transition (application.transition). The detail view lists the available transitions, fires one on click, and reloads. This replaced the dropped approval accept/reject UI + the tasks-tab inline decide. The tasks tab now lists only vote tasks. The user acts on a vote task by opening the detail view.

## Frontend editor (admin/flow)
State kinds are normal and vote. The guard builder has an op dropdown. It offers the actor ops only when the transition is manual. Each op gets a value control: role and committee selects, a bool checkbox, free text, or a compare sub-form with field, op and value. The editor has 4 action config forms: webhook select, notify recipient-list builder, addToNextSession committee select, assignBudget free-text id. `guard-builder.util.ts` mirrors the backend validation. Both assignBudget and budgetIs use a FREE-TEXT budget id. There is no cost center tree picker, so this stays a light spot.

## Verification / caveats
Backend unit tests green (pre-existing failures in antiabuse/auth/files/pdf_nextcloud/worker_mail are NOT ours — confirmed against the pre-work commit). Integration tests ported to the branch model but DB-gated → CI-verified only. Angular build clean. NO dedicated tests yet for FlowExtrasActionDispatcher or gremium/email recipients (webhook dispatch_to_webhook IS covered). The user must run migrations 0038/0039 + rebuild.

See [[antragsplattform-backlog]], [[budget-kostenstellen-spec]]. Work autonomously [[work-autonomously]]. Write i18n strings in both de and en [[admin-domain-rules]].
