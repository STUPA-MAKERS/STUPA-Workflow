---
name: antragsplattform-backlog
description: Outstanding feature backlog for the antragsplattform (StuPa application platform) as of 2026-06-08
metadata: 
  node_type: memory
  type: project
---

Branch `feat/admin-ux-flow-editor-fixes` (PR #126).

DONE 2026-06-09 (meetings overhaul, pushed): **forced gremium-roles**
vorstand/schriftfuehrung/member in EVERY gremium (seed on create + lazy on list + migration 0031
backfill, delete-guard, GremiumRoleOut.forced flag, FE roles page hides delete). **Meeting
control needs the meeting lead** — the authoritative PATCH /meetings requires the vorstand or
schriftfuehrung gremium-role, or admin. MeetingOut.canControl drives the FE hide of the control
and planning cards (LEAD_ROLE_KEYS in admin/gremium_roles.py, MeetingService.can_control).
**Attendance** (#55/#56): meeting_attendance table (migration 0032) + AttendanceService (roster =
the current gremium_membership, present/excused/absent, source self or lead), GET
/meetings/{id}/attendance, PUT …/attendance/me (member self), PUT …/attendance/{principalId}
(lead), FE attendance card. **Protocol autosave** (#56): debounced PATCH, no manual save button,
Saving/Saved status. **Markdown preview** upgraded without a new dependency: pipe tables, links,
ordered lists and HR in meetings.util.renderMarkdown. **ALTCHA fix**: the widget was a stub that
emitted 'altcha-stub-solution'. It is now a real PoW solver (GET /altcha/challenge + Web-Crypto
SHA-256 brute force + base64), and 404 means unavailable. The stub caused the submit 422 "Altcha
verification failed". Also: gremium-role dialog input styling, flow-editor edges start at the
branch dot + bezier, breadcrumbs single-source in budget style with no Dashboard prefix,
borderless user-icon account menu, members route → /admin/gremien/:id/members.

DONE this session: #9 budget cost-center tree (FE on the existing /api/budgets backend), #11
per-Gremium members (Gremien admin), #12 Users Nextcloud-table + roles split (/admin/roles) +
admin role locked. Plus the earlier UX and flow rounds.

Also DONE: #14 per-Gremium vote-delegation flag, #17 budget-statistics drilldown, #18 Gremien
rework, #22 budget↔gremium decoupled + FY inside + per-row limit dialog.

Also DONE: #20 (the user then asked to REMOVE the templates again), shared DataTableComponent
(#26 started, Gremien migrated), Votes nav tab removed (voting runs through meetings), budget
statistics page decluttered.

BIG OPEN REDESIGNS (need design and scoping before we build them):
- **#28 GLOBAL flow redesign** — one global flow with global states, not one flow per application
  type. Special VOTING states ("Gremium X must vote") replace the voteResult auto-transition. Add
  states where "role X in gremium Y accepts or rejects". Decision nodes route by amount, type or
  applicant role. Keep gremium-roles and global roles clearly apart. Large BE+FE. Supersedes #23.
  Design decided: drop all existing entries (pre-alpha hard cutover), two fixed outputs per vote
  or approval state, backend model and engine FIRST. The BE model is already started (State.kind
  CHECK/vote/approval/decision + config JSONB, Transition.branch,
  FlowVersion.application_type_id nullable + global/per-type partial unique indexes,
  config_schemas validation, migration 0023).
- **#42 Gremium-roles model** (ties into the gremium-vs-global split of #28): inside a Gremium a
  user holds EXACTLY ONE role at a time. Gremium-roles are a SEPARATE role set from the global
  roles, configured on their own page below admin/gremien/. An assignment uses a dropdown of
  gremium-roles. Gremium membership is TIME-BOUNDED (valid_from/valid_until = the term of
  office). Global roles are PERMANENT and INDEFINITE with no expiry, so drop the validity window
  from the global-role assign UI on admin/users. Several NON-OVERLAPPING memberships of the same
  gremium are allowed (consecutive terms), overlapping ones are forbidden. Current bug: a user
  can hold several simultaneous roles in one gremium, which is wrong.
- **#46 Granular permissions everywhere** — audit every admin or action endpoint and every UI
  control, then gate each one behind a SPECIFIC granular permission, not behind broad admin. The
  BE checks are authoritative. The FE hides or disables. Big cross-cutting change.
- **#45 Audit-Log tab** — an admin view of the append-only audit trail, gated by a dedicated
  permission, for example audit.read.
- **#13 Form-Builder** like Nextcloud Forms (plus an admin "Applications" tile and list, add via
  dialog).
- **#26 finish** the migration of all tables to the shared DataTable. Everything becomes a shared
  component.
- **#29 Site settings** — replace the versioned "Branding & Texts" page with a direct edit of the
  current values.

DONE 2026-06-08 (full-auto run, all on the branch + pushed): uniform row height (DataTable fixed
3rem), #40 self-admin-remove guard, #41 delete Gremium, #43 equal admin tiles, #44 self-suspend
guard + UI, #47 icon-button tooltips (shared Button title→ariaLabel), #48 role-tags scroll, #49
budget applications stacked, #50-fix role-tag × inside the badge, #15 admin=all-rights
(Principal.has), #51 header account popout (logout only there), #52 theme toggle neutral in dark,
#53 lang chevron mask, #54 dashboard gremium badges, #39 webhooks+notifications reworked to
header+DataTable+dialog, #45 Audit-Log page (GET /admin/audit, audit.read). #28 ENGINE: the
decision DSL in flow/routing.py, FlowService.route_decision, fire_branch, branch_transition and
submit_approval, plus _has_gremium_role, POST /applications/{id}/approval, a vote close fires the
pass or fail branch, and application creation uses the active global flow.

#60 FLOW-UI DONE (2026-06-08, pushed): approval Accept/Reject on the application detail (POST
/approval, StateOut.kind added in the BE). The flow editor authors state.kind
(normal/vote/approval/decision) plus a per-kind config: vote → gremium, approval → role-source
toggle (a gremium-role OR a global role), decision → rules builder field/op/value→target plus
else. It also authors the transition branch (pass/fail/accept/reject). The editor is GLOBAL and
has no type dropdown. It loads and saves the active global flow through GET/POST
/admin/flow-versions/global. Client-side kind validation mirrors the BE, so a save shows the
specific error, for example "vote needs pass+fail". BE: an approval may omit gremiumId, which
turns it into a global-role decision. The graph serializer carries kind, config and branch.

#62 PER-GREMIUM ROLES (2026-06-08, pushed): gremium_role now has a gremium_id FK (migration 0027,
Unique(gremium_id,key)). The endpoints live under /admin/gremien/{id}/roles. The FE roles page is
a SUBPAGE at admin/gremien/:id/roles, linked from the edit icon of the gremien table. REMAINING
for #62: the per-gremium **members** view still uses the global RoleAssignment. It needs a
gremium-membership assignment UI (a dropdown of the roles of that gremium + term of office +
list/delete) on /admin/gremien/{id}/memberships.

DONE 2026-06-08 batch 3 (pushed): #61 the member role is auto-granted on every login and nobody
can remove it. #62 FINISHED — the gremium members subpage assigns gremium_membership (the roles
of this gremium + term of office, overlap → 409), and FlowService._has_gremium_role now uses
gremium_membership/gremium_role. #63 route-driven breadcrumbs in the shell. #64 Tasks tab (GET
/applications/tasks → the vote and approval applications the principal can act on, FE nav + table
→ detail). #65 table top spacing. #66 flow builder polish (a vote or approval node shows one
labelled out-dot per branch, pass/fail or accept/reject, a drag presets the branch, the kind
label sits on the node, the intro blurb is gone). NEXT MAJOR (user-queued): #13 NC-Forms-style
form builder. The current form-builder is a flat field list. It needs a forms list + add dialog →
per-form NC-style editor: title + Markdown description, +Add-question type menu, drag-reorder,
View/Edit toggle.

#13 FORM-BUILDER DONE (2026-06-09, pushed, commit 2731ad3): NC-Forms rework. `admin/forms` is now
a FormsListComponent (DataTable of application types + add-via-dialog: title DE/EN, Gremium,
hasBudget, key auto-slug → navigate to the editor). `admin/forms/:id` = FormEditorComponent
(NC-style): title + multilingual Markdown description, View/Edit toggle, question cards (type
menu through app-select with friendly labels, label/help DE+EN, required, options, advanced ⋯ =
key/PII/promote/validation/JsonLogic, drag + arrow reorder, duplicate/delete), "+ add question"
type menu. It reuses form-field.util. The OLD form-builder component is DELETED. The admin-home
overview edit icon deep-links to the editor. BE: form_version.description_i18n (migration 0028),
FormVersionCreate/Out carry the description, and a new admin GET
/admin/application-types/{id}/form-versions/latest → FormDraftOut (raw fields + description) for
editing (service.get_form_draft). admin-api:
listApplicationTypesFull/createApplicationType/updateApplicationType/getFormDraft +
createFormVersion(typeId,fields,description), mock store MOCK_APP_TYPES + MOCK_FORM_DRAFTS. i18n
DE+EN: admin.forms.* + admin.form.type.* + admin.common.cancel/delete. Specs: forms-list +
form-editor. NOTE: the Markdown description renders as pre-wrap plain text (no Markdown library).
That is safe and injects no HTML. Upgrade it later. The BE create-application-type and PATCH
endpoints already existed.

#16 EN-EDITING DONE (2026-06-09, pushed e82a0e6): the branding/site-config editor now has EN
inputs for the copyright, the legal-link labels, the footer-link labels and all 4 freetexts
(login/welcome/support/emailFooter) — two columns DE/EN (.br__bi). Composite aria-labels
"<field> (DE)/(EN)". Spec added.

#21 ALREADY DONE: the roles page has an add-dialog (createRole), a delete (deleteRole) and
permission edit (saveRolePermissions). The backlog entry is stale, nothing to do.

#25 BUDGET-EXPENSE DONE — BACKEND ONLY (2026-06-09, pushed dc3e81f): a standalone expense against
a cost center + fiscal year, with no application. New budget_expense table (budget_id,
fiscal_year_id, amount>0 EUR, description, actor), migration 0030. POST/GET
/api/budgets/{id}/expenses (create P(budget.manage), list P(budget.view), node+subtree,
?fiscalYear filter) + DELETE /api/budget-expenses/{id}. Expenses fold into the get_tree
committed_rows and roll up through the path_key prefix exactly like approved applications
(consumed↑, available↓). The FY comes from the request or from the single active FY of the top
node (ambiguous → 422). Tests: router wiring + RBAC, _resolve_expense_fiscal_year branches,
rollup. REMAINING #25: the FE UI to book and list expenses on the budget tree
(budget-tree.component) is NOT done. We deferred it to avoid a collision with the other agent in
the FE.

NOTE 2026-06-09: a SECOND agent works on the FE (breadcrumbs/forms/form-editor, then
meetings/attendance + gremium forced-roles). Hands off form-editor, meetings, attendance and
shell. They commit with `git add -A`, which can sweep up your uncommitted edits to shared files.
That happened with models.ts and mappers.ts. Stage your own files explicitly and commit promptly.

#24 LOGGED-IN APPLY DONE (2026-06-09, pushed f3f131c BE + 078fc19 FE): the user reframed #24 as
the apply flow from the dashboard for logged-in users, NOT admin-on-behalf. (1) Logged-in users
skip ALTCHA. (2) The email and the name come from the account. BE: a new
require_altcha_unless_authenticated dependency on POST /applications skips ALTCHA when a
principal is present and still checks anonymous callers. ApplicationCreate.applicant_email is now
OPTIONAL. The router derives email = payload or principal.email, name = payload or
principal.display_name, actor = principal.sub else "applicant", and an anonymous request without
an email gives 422. ApplicationsService.create gained an actor parameter (StatusEvent +
SubmissionVersion.changed_by). We dropped the earlier admin-on-behalf /admin/applications
endpoint idea as redundant, because a logged-in manager passes applicantEmail. FE: the
apply-wizard injects AuthService and drops the contact step and the ALTCHA widget when loggedIn
(sectionBase 1 instead of 2). It sends a null email and a null altcha, since the backend derives
them, and the review shows the account email. models.ts
ApplicationCreateBody/NewApplication applicantEmail + altcha are now nullable, and the mapper
uses ?? null. Tests BE+FE.

#13 EXTRA DONE (2026-06-09, pushed): **budget toggle + metric dropdown** (6b8adb1): the "with
budget" toggle (has_budget) now sits in the form EDITOR meta and persists through PATCH
/admin/application-types together with the title. The "target metric" (promoteTarget) is now a
DROPDOWN of valid metrics, and only `amount` is wired — PROMOTE_TARGETS in form-field.util.ts.
Turning on isPromoted defaults the target to amount.
**positions field type + system title** (BE b48bc11, FE dcc389f): every application MUST have a
title. effective_form auto-prepends a required system `title` text field to the main section
unless the form already defines one (validation.system_title_field/SYSTEM_TITLE_KEY). New
`positions` FieldType (cost positions): the value is a list of {label,
offers:[{label,value,preferred}]}. Validation _validate_positions requires at least minPositions
(default 1), each with at least minOffers (default 3) offers, exactly one preferred, and finite
values above 0. It implicitly promotes the sum of the preferred offer values into `amount`
(extract_promoted positions branch, no isPromoted flag). FieldValidation gains minOffers and
minPositions. FE: the form-editor has a positions config block (minOffers/minPositions), plus a
custom Formly type FormlyPositionsType (shared/formly/types) — a repeating Position→Offers
editor, a preferred radio, a live total, and validity mirrored to the formControl through
revalidate, in ngOnInit too, so an empty field is invalid. It is registered in formly.providers.
The formly-mapper maps positions → 'positions' and passes the minOffers and minPositions props.
The apply-wizard review shows the total. NOTE: only the `amount` promote target is consumed
downstream. Other targets are extracted but unused. We did NOT reserve the `title` key, because
that means too much fixture churn, and the inject-if-absent in effective_form is enough.
APPLICATION DETAIL FIX (a5455b9): the detail page rendered raw data keys and blank transition
pills. Now the data uses effective-form field labels (api.effectiveForm(typeId), fetched next to
the application, degrades to raw keys) plus type-formatted values (select/multiselect option
labels, localized currency, checkbox yes/no, positions count + total). The system `title` is
omitted, because it is the heading. A transition with an empty label falls back to the generic
label ("Weiter" in DE, "Advance" in EN). refresh() does NOT refetch the static form, only
loadApplication does, so the spec flushAll has a form=true parameter.

SESSION 2026-06-09 LATE (many commits pushed, branch feat/admin-ux-flow-editor-fixes):
- positions field type (BE config_schemas + validation, FE custom Formly type
  shared/formly/types/formly-positions), the system `title` field auto-injected by
  effective_form, positions auto-promotes the sum of the preferred values → amount.
- form builder: the key sits at the top of the question card, budget toggle + metric dropdown in
  the editor, type-aware advanced panel (no promote on a non-numeric field, which fixes the 422
  "promoted must be numeric"), positions config minOffers/minPositions.
- application detail: typed and labelled data through the effective form, the manual "Status
  change" transitions card removed (the flow drives it), email row, INLINE EDIT (Formly) and
  DELETE gated on canEdit, positions total.
- #24 creator access: application.created_by (migration 0034) is set on a logged-in create,
  require_app_read/edit fall back to the creator, DELETE /applications/{id},
  ApplicationOut.canEdit.
- title column in the Applications and Tasks lists (BE ApplicationListItem.title from
  data['title']).
- tasks: inline accept/reject (approval) and Open (vote).
- attachments persist: NEW GET /applications/{id}/attachments + FE listAttachments, and the panel
  hydrates on init. The data was always in the DB and MinIO, there was only no list endpoint.
- removed the unimplemented tab that listed the Gremien of the user.
- #20 applications table: rounded border + filter POPOUT (button + funnel icon + active-count
  badge) + amount-range and date-range filters + sortable amount and created headers. The BE list
  gained amountMin/Max, createdFrom/To, sort and order.
REMAINING (files contended with the other agent — coordinate): #17 flow editor (branch filter by
node kind, roleKey reactivity only shows after a reselect, decision node + decision-question
field, NEW applicant-submit node kind, reject free-text reason). #22 budget ((auto-)assign an
application to a budget — the BE assign-budget endpoint EXISTS, the FE is missing, fiscal year
year-only + start on budget, rename "Top-Budget" → "Budget"). #20 leftovers (cost-position
subtree filter, all-states list). GOTCHA: a type=number ngModel emits a NUMBER, not a string,
which broke v.trim() in the active-filter count → use String().

GOTCHA — THE LOCAL .env ENABLES ALTCHA: backend/.env sets ALTCHA_HMAC_SECRET → altcha_enabled is
True locally → about 6 to 8 tests that expect ALTCHA "disabled"
(test_antiabuse/test_applications_router/test_auth_router) FAIL locally but PASS in CI, which has
no .env. conftest assumes ALTCHA is OFF. To run those locally in the CI style, do
`mv backend/.env aside` and then run pytest. Do not chase these as bugs.

#42 PROGRESS (2026-06-08): backend DONE — gremium_role + gremium_membership tables (migration
0026), GremiumRoleService with the pure intervals_overlap helper (one active role per principal
and gremium, consecutive non-overlapping terms OK), admin endpoints /admin/gremium-roles +
/admin/gremien/{id}/memberships + /admin/gremium-memberships/{id}. The FE catalog page
admin/gremium-roles is DONE (CRUD). REMAINING: the membership-assignment UI on the per-gremium
members subpage (assign a gremium-role + term-of-office window through a dropdown, list and
delete memberships). That page still uses the global RoleAssignment and needs the switch to the
new gremium_membership API.

NEW BIG BACKLOG (2026-06-08, not started): #50 applications table (rounded border, lazy infinite
scroll, the SAME table reused under Budget with a filter, rich filter pop-out: cost-center tree
including the subtree, amount-range slider, active-filter hint badge). #55 attendance confirm or
excuse per planned meeting (per-gremium lead-time window). #56 protocol editor: Markdown library
+ live server save + actual-attendance picker. #57 attendance statistics per member over the term
of office (excused/unexcused/present). #58 native agenda-item list in the protocol (an agenda
item is an application or free text). #59 Excel export of budgets and applications
(filter-aware). #46 granular permissions everywhere. #42 gremium-roles model (see above).

SMALLER OPEN:
- #19 add-via-dialog everywhere. #21 configurable roles (the BE has POST/PATCH /admin/roles). #24
  manual application creation. #25 standalone budget expenses. #27 meetings dialog + shared
  table. #15 admin=all-rights in the BE. #16 EN editing everywhere.

STILL OPEN:
- **#20** flow editor: drop Expert mode, savable templates, more help text. See
  [[ui-patterns-and-backlog2]].
- **#21** configurable roles (create/edit/delete) — the backend already has POST/PATCH
  /admin/roles, so add the FE role CRUD.
- **#23** flow rule: an amount threshold routes to a specific gremium vote (guard +
  gremium-scoped action).
- **#24** manual application creation as a manager (permission + UI).
- **#25** budget expenses independent of an application (a standalone expense against a budget
  node + FY).
- **#10 Meeting agenda** — assign applications to meetings (Image 12). The backend has only a
  single `activeApplicationId` and `POST /applications/{id}/votes`. There is no agenda model yet.
- **#13 Form-Builder** — rework it almost 1:1 like Nextcloud Forms (large FE rewrite). See
  [[nextcloud-parity-ui]].
- **#14** vote delegation → a per-Gremium setting (the per-user checkbox is already removed, it
  still needs a Gremium flag + UI). See [[admin-domain-rules]].
- **#15** enforce admin=all-permissions in the BACKEND (the FE already locks it). See
  [[admin-domain-rules]].
- **#16** allow EN editing for all i18n values, not only DE (branding/gremium/form labels). See
  [[admin-domain-rules]].

SESSION 2026-06-09 NIGHT (pushed, branch feat/admin-ux-flow-editor-fixes):
- tasks: iconic accept (green check) and reject (red cross) for approval rows, Open button
  removed (a row click opens the detail), added a `success` Button variant and a `check` Icon
  (5d44ce5).
- admin breadcrumbs: every admin sub-route carries parent:['admin'] (nested →
  ['admin','admin/forms'] and so on), so the crumbs link back to /admin (5d44ce5).
- gremium-roles edit-button alignment (Image#4): a forced role now shows a DISABLED delete button
  of the same size instead of a wide "required" label, so the edit pencil stays aligned
  (5d44ce5).
- flow editor: ONE output dot per distinct guard on normal nodes, plus a catch-all dot for new
  edges. Edges start at the dot of their guard. The state inspector lists the guards in
  evaluation order with ↑/↓ controls that restamp Transition.order, and the first match wins. The
  backend already does this: admin/service.py falls back to order=enumerate(transitions), and
  flow/service uses order_by(Transition.order) (845b3d2).
- positions field: offer-remove is disabled at minOffers, the value input formats on blur (it
  parses 1.234,56 and 1234.56), and errors are INLINE (invalid inputs turn red with a concise
  per-card message instead of a notice at the bottom) (96d05be + earlier).
- application detail: the full cost-position breakdown (each position with its offers, the
  preferred one highlighted, positions total) is read-only, and the edit-form Formly fields are
  spaced vertically (Image#5 spacing) (96d05be).

MULTI-STEP + DEADLINES DONE 2026-06-09 NIGHT (pushed 50e8b29 + 2e76ba5):
- **MULTI-STEP FORMS** (50e8b29): a new `section` FieldType acts as a divider marker with a label
  only. The backend effective_form() splits the main fields at the markers into titled
  FormSections. It injects the title into the FIRST section AFTER the split, so a leading marker
  does not create a title-only step. It strips the markers from the fields and skips them in
  validate_answers. FormSection gained `label`, and the service uses s.label or the
  SECTION_LABELS fallback. FE: the form-editor has '+ Section' (auto-key section_N, a title-only
  card + a preview divider), formly-mapper filters the section out, and models.ts and
  form-field.util add section to FIELD_TYPES. The apply wizard already steps per eff.section, so
  authored sections become steps for free. Tests BE (test_forms_validation split/leading/skip)
  and FE (the mapper drops markers).

SESSION 2026-06-09 (continuation, pushed):
- **TASKS mock fix** (0d473b0): mock-api.interceptor had NO `/applications/tasks` handler, so the
  single-app catch-all `/\/applications\/[^/]+$/` returned one object instead of an array, which
  broke the Tasks page under USE_MOCK_API. Added MOCK_TASKS (approval and vote rows the principal
  may act on) plus a POST `/applications/{id}/approval` handler that splices the decided row, so
  it vanishes on reload.
- **DEADLINES ENFORCEMENT WIRING DONE** (a874987): the deferred follow-up is now built. The state
  config carries `deadlinePolicyKey`. FlowService.schedule_state_deadline(app, state) resolves
  the policy (resolve_due_at, created_at/updated_at references) and creates a Deadline whose
  action_on_pass points at the `deadlinePassed`-guarded transition of the state, found through
  the module function `_guard_fires_on_deadline`, which scans and/or/not recursively. It clears
  prior unfired flow_deadline rows first. applications.service.create calls it for the initial
  state after commit and refresh, and flow.service.fire calls it for to_state after commit and
  refresh. The T-44 cron fires it. Flow-editor: the state inspector has a deadline-policy
  `app-select` (it loads listDeadlinePolicies) plus setStateDeadlinePolicy and a hint. The config
  passes through normalizeFlowGraph wholesale, so no migration is needed. i18n
  admin.flow.cfgDeadline/cfgDeadlinePh/cfgDeadlineHint de+en. Tests: guard scanner,
  schedule-creates-row, and no-op-without-key (test_deadline_policies, 10 pass). The flow-editor
  spec mock got listDeadlinePolicies. NOTE: the 3 local ALTCHA-.env failures
  (test_antiabuse/test_applications_router) are the known GOTCHA and pass in the CI style.

- **DEADLINE-POLICY REGISTRY** (2e76ba5): deadline_policy table (migration 0037) — key (unique) +
  label + kind ('absolute'|'relative_submitted'|'relative_changed') + absolute_at + offset_days.
  resolve_due_at(policy, submitted_at, changed_at) is a pure helper. Admin CRUD
  /admin/deadline-policies (admin.config) in deadlines/router.py (DeadlinePolicyService),
  registered in main.py and models.py. FE admin 'Deadlines' page (pages/admin/deadlines, DataTable
  + dialog, kind-aware date or offset), route admin/deadlines (parent ['admin']) + admin-home
  tile + i18n admin.deadlines.*. Tests BE (resolve + router) and FE (component spec). REMAINING
  follow-up (NOT done): the ENFORCEMENT wiring — a flow state config references a policy key, so
  on entering the state, resolve_due_at plus DeadlineService.create make a Deadline row
  (action_on_pass=transition) and the existing T-44 cron fires deadlinePassed. It also needs
  flow-editor UI to pick a policy key on a node. The guard op `deadlinePassed` (shared/guards.py,
  ctx.deadline_passed bool) and the cron substrate already exist.

OLD QUEUE (now built above):
- **MULTI-STEP FORMS** (decision: "section field = step"). The apply wizard ALREADY steps per
  eff.section. The builder is FLAT (one fields[] list) and the backend effective_form lumps all
  type fields into ONE "main" section. PLAN: add a `section` FieldType, a divider marker that
  carries an I18n label. The backend effective_form() splits main_fields at each `section` marker
  into several FormSection(label=marker.label) and strips the markers from the fields. The
  FormSection dataclass needs `label`, and the service uses s.label with the SECTION_LABELS
  fallback for main and budget. validate_answers and extract_promoted must SKIP type=='section'.
  The FieldType union needs 'section' in config_schemas.py AND in the FE models. The form-editor
  +Add menu gets "Section" (auto-key section_N, only the label is editable, render it as a
  divider). Apply and detail already consume eff.sections.fields, because the server strips the
  markers, so multi-step comes for free. Needs BE and FE tests.
- **FLOW DEADLINES = NAMED POLICIES** (decision: "Named deadline policies"). A new admin
  "Deadlines" page plus a backend module. A DeadlinePolicy has a key and a kind: absolute (a
  date, set per semester, editable at any time WITHOUT touching the flow) OR relative (submitted
  + X days, or lastChange + X days). Flow nodes and types reference a policy by key. Enforcement
  reuses the existing `deadlinePassed` guard op (flow). PLAN: a backend deadline_policy table +
  CRUD (admin.*), resolve(policy, app) → a concrete datetime (the absolute value, or
  app.created_at/updated_at + X days), the flow guard `deadlinePassed` reads the referenced
  policy, an admin Deadlines CRUD page (per-semester date edit, relative offsets), and the flow
  editor lets a node reference a policy key. Big BE + FE + migration.

Stack: Angular 20 frontend (signals, standalone, Jest + testing-library, `npm test` = jest, needs
`npm install`, because the workspace ships partial node_modules). Backend: FastAPI + arq worker +
SQLAlchemy/Alembic (the venv lacks pytest by default). i18n is a typed `de`/`en` catalog in
`core/i18n/translations.ts`, so add every key to both.
GOTCHA 2026-06-09 night: the IN-PROGRESS markdown-editor/ (untracked) and meetings.component.ts
(savingTop) of the other agent break `ng build` in the working tree. Those are NOT your files.
Verify your changes with an isolated `jest <area>` and stage only your own files.

SESSION 2026-06-09 (TASKS.md run, branch feat/admin-ux-flow-editor-fixes):
- TASKS.md = a NEW 11-task list (admin UX and platform), with its own numbering, separate from
  this backlog. Working through it.
- TASK#1 DONE: admin-home restyled — icon-left tiles (added the icons building, euro, form, flow,
  palette, webhook, bell, audit, clock and export to IconComponent), removed the active-forms
  table, shortened the users and gremien descriptions. Spec rewritten.
- TASK#2 DONE: Excel export. New permissions budget.export (admin/finance/manager) and
  application.export (admin/manager) in PERMISSION_CATALOGUE and in admin.mock
  MOCK_PERMISSIONS. Migration 0043_export_permissions. It ALSO FIXED a multi-head: two 0041
  revisions (budget_color_states and agenda_freetext_fix, both off 0040) were linearized to
  budget_color_states → 0042_agenda_freetext_fix → 0043. The openpyxl dependency was added and
  installed in the venv. BE: GET /api/budget/export.xlsx (tree_router, node/fiscalYear/gremium
  filters, _find_subtree) and /api/applications/export.xlsx (router, reuses list_applications
  with limit 100k). The xlsx builder is app/shared/xlsx.py (lazy openpyxl). Service helpers:
  BudgetTreeService.fiscal_year_label_map and ApplicationsService.name_maps. FE: exportXlsx on
  BudgetTreeApi, exportApplicationsXlsx on ApiClient, a shared downloadBlob util, and gated
  buttons on budget-dashboard and applications-list. i18n budget.export and
  applications.list.export de+en. Tests: 46 pass (test_budget_tree_router +
  test_applications_router).
- GOTCHA: the .env MUST stay present for create_app, because the settings need database_url and
  others. Move it aside only for ALTCHA-sensitive pytest runs.
