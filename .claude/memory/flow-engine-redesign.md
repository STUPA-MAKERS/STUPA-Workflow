---
name: flow-engine-redesign
description: "Canonical design of the redesigned flow engine — state kinds, guard catalog, actions, permissions, manual-transition UI. All decisions confirmed via question tool."
metadata: 
  node_type: memory
  type: project
---

Flow-engine redesign, branch feat/admin-ux-flow-editor-fixes (2026-06-09, DONE, 7 commits pushed). Every decision below confirmed with the user via the question tool — no assumptions. This is the authoritative design record.

## State kinds
- Keep `normal` + `vote` ONLY. Dropped `approval` + `decision` (approval = manual `roleIs` transition; decision = automatic guard transition — both redundant). Model CheckConstraint `kind IN ('normal','vote')`, migration 0038 cuts over existing approval/decision rows → normal.
- `vote`: a Gremium votes. `config.gremiumId` required, exactly 2 outgoing transitions with `branch` `pass`/`fail`. Vote close (voting/service) fires the branch via `flow.fire_branch(branch_name)`: passed→pass, rejected/tie→fail (tie is fail-closed). vote.result_branch_transition_id records the fired branch.

## Transitions
- `automatic` flag (auto-fires when guard true, worker/cron, manual=False) vs manual (user fires from detail view). NO separate actor field — actor gating is via guards.
- `branch` (pass/fail) only on vote-state outgoings.

## Guard catalog (shared/guards.py, mirrored in guard-builder.util.ts)
Single-operator dicts, whitelist, no eval. Leaf ops:
- **Conditions (auto + manual):** `deadlinePassed`(bool), `applicantRoleIs`(global role key), `applicantCommitteeIs`(gremium id — ANY active membership), `budgetIs`(assigned Kostenstelle = application.budget_id), `budgetFitsApplication`(bool: amount ≤ allocation − Σ direct BudgetExpense of the assigned node+fiscal-year), `hasField`(field key present/non-empty), `compare`.
- **Actor gates (MANUAL only):** `roleIs`(actor global role), `isInCommittee`(actor gremium id — ANY active membership). validate_guard(allow_actor_ops=not t.automatic) rejects these on automatic transitions.
- Combinators: `and`/`or`/`not`.
- REMOVED: `permissionIs`, `voteResult` (→ vote branches), `manual` (→ automatic flag), `fieldsComplete` (→ hasField/fieldValueIs; submit-completeness still enforced at patch/submit).

### `compare` guard — typed, over ANY form field by key
`{"compare":{"field":"<key>","op":"<op>","value":<v>}}`. `field` = any form-field key OR built-in `amount`(currency). Value type inferred at runtime from the field def (number/currency→numeric, date→date, checkbox→bool, else text). Op set by type: numeric/currency/date `== != < <= > >=`; text/select `== != in` (in→list); bool `==`. Wrong-op-for-type raises. Replaced the earlier valueLargerThan/SmallerThan + fieldValueIs ideas (user: "use generic promoted values, manage differing types"). Editor offers all COMPARE_OPS + free-text value (field type unknown at edit time for a global flow).

### Guard context (flow/context.py, async, loads from DB)
manual flag; actor roles + actor_committees (only when manual); applicant_roles (data['_applicantRoles']) + applicant_committees (created_by sub memberships); budget_id; budget_fits; field_values (data + amount) + field_types map.

## Actions (3 kept + 1 added, implemented properly — not stubs)
ACTION_TYPES = `{webhook, notify, addToNextSession, assignBudget}`. Dropped exportPdf/setEditLock/budgetReserve/budgetBook/openVote/requeue. Dispatch chain in main.py: notify-dispatcher + webhook-dispatcher + FlowExtrasActionDispatcher (addToNextSession+assignBudget). Post-commit, idempotent via DispatchedAction.idempotency_key `app:statusEvent:index:type`.
- **webhook**: `{webhookId}` references an existing admin/webhooks entry (NOT inline url, NOT event-fanout). WebhookService.dispatch_to_webhook creates one delivery for that hook, event `application.transition`, payload {applicationId,transitionId,statusEventId}, dedup on (webhook_id, idempotency_key).
- **notify**: `{recipients:[{kind,ref?}]}`. Kinds: `gremium`(all current members' emails), `role`(global role holders), `applicant`, `email`(literal). RecipientResolver extended with gremium + email. Reuses NotificationService.handle_notify_action (needs templateKey for an actual mail).
- **addToNextSession**: `{gremiumId}`. ONLY valid on a transition whose target state kind==vote (validated in flow graph). Dispatch → earliest FUTURE Meeting of the gremium (date ≥ today, not finalized) → AgendaService.add. No upcoming meeting → log warning + no-op (skip, do NOT auto-create).
- **assignBudget**: `{budgetId}`. Sets application.budget_id to the Kostenstelle; derives fiscal_year from the single active HHJ of the top-level node (else leaves open).

## Permissions — reworked to 16 keys (shared/permissions.py)
application.read, application.create, application.transition (gates manual firing — flow router uses this, was application.manage), application.manage, form.configure, flow.configure, vote.cast, vote.manage, meeting.manage, budget.view, budget.manage, notification.manage, webhook.manage, audit.read, admin.config, admin.roles. DROPPED: application.update(→manage), protocol.manage + protocol.write(→meeting.manage; protocol router now gates on meeting.manage). Migration 0039 carries over grants (manage→transition, protocol.write→meeting.manage) + deletes dropped keys.

## Manual-transition UI (application detail)
GET /applications/{id}/transitions (guard-filtered, manual-only) + POST .../transition (application.transition). Detail lists available transitions, fires on click, reloads. Replaced the dropped approval accept/reject UI + the tasks-tab inline decide (tasks now lists only vote tasks, acted on by opening the detail).

## Frontend editor (admin/flow)
normal/vote state kinds; guard builder with op dropdown (actor ops only when manual) + per-op value control (role/committee selects, bool checkbox, free text, compare sub-form field+op+value); 4 action config forms (webhook select, notify recipient-list builder, addToNextSession committee select, assignBudget free-text id). guard-builder.util.ts mirrors backend validation. assignBudget/budgetIs use FREE-TEXT budget id (no Kostenstelle tree picker — light spot).

## Verification / caveats
Backend unit tests green (pre-existing failures in antiabuse/auth/files/pdf_nextcloud/worker_mail are NOT ours — confirmed vs pre-work commit). Integration tests ported to branch model but DB-gated → CI-verified only. Angular build clean. NO dedicated tests yet for FlowExtrasActionDispatcher or gremium/email recipients (webhook dispatch_to_webhook IS covered). User must run migrations 0038/0039 + rebuild.

See [[antragsplattform-backlog]], [[budget-kostenstellen-spec]]. Work autonomously [[work-autonomously]]; i18n de+en both [[admin-domain-rules]].
