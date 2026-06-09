# Admin UX & Platform Tasks

Branch: `feat/admin-ux-flow-editor-fixes`

**Status (2026-06-10):** Done — #1, #2, #5, #6, #8, #10. Open — #3, #4, #7, #9, #11.

**How to use this file**
- Each task is a `- [ ]` checkbox. Tick it when done.
- Subtasks under each task can be copied straight into your todo list.
- **Ask before guessing.** If anything is ambiguous and affects data model, permissions, or removal of features, ask the user before proceeding.
- Edit all i18n in **both** `de` and `en` (`frontend/src/app/core/i18n/translations.ts`).
- Admin = all rights. New global permissions must be added to the admin role seed.

---

## 1. Admin dashboard restyle
Target: `frontend/src/app/pages/admin/admin-home.component.ts` (the `/admin` landing).

- [x] Shorten each tile description to one short line
- [x] Add a fitting large icon to the left of each tile title
- [x] Make tiles look intuitive / modern (icon-left layout, consistent card sizing)
- [x] Remove the "active forms" section at the bottom (the form-overview table)
- [x] Update tile description i18n keys (de + en)

---

## 2. Excel export — budget + applications
Two separate global permissions, real `.xlsx` output (openpyxl). Default grants: `budget.export` → finance + manager, `application.export` → manager. Exports honour the currently active filters; budget export covers the whole tree filtered by current year/selection.

- [x] Add global permissions `budget.export` and `application.export`
  - [x] Add both to `ALL_PERMISSIONS` and to admin role in `backend/migrations/versions/0003_seed_roles.py` (or new migration)
  - [x] Grant `budget.export` to finance + manager, `application.export` to manager
- [x] Backend: add `openpyxl` dependency
- [x] Backend: `GET /api/budget/export.xlsx` (respects current budget filters), gated by `budget.export`
- [x] Backend: `GET /api/applications/export.xlsx` (respects current list filters), gated by `application.export`
- [x] Frontend: export button on budget tab (`budget-dashboard.component.ts`), visible only with `budget.export`
- [x] Frontend: export button on applications list (`applications-list.component.ts`), visible only with `application.export`
- [x] Exports honour active filters/search (budget tree node, year; app state/gremium/type/budget/q)
- [x] i18n for buttons + permission labels (de + en)

---

## 3. Cost-center roles → filtered budget visibility
New CC-scoped assignment table linking **global roles** ↔ cost-centers. A user sees a cost-center and its children; user sees the budget tab (filtered) if at least one of their roles has a cost-center assigned.

- [ ] Backend: new model linking global Role ↔ cost-center (`Budget` node in `budget/tree_models.py`)
  - [ ] Migration for the new table
  - [ ] Resolve assigned cost-centers for a principal in RBAC (`auth/rbac.py`)
  - [ ] Expand to children via `path_key` / `parent_id` subtree
- [ ] Backend: budget tree endpoints filter to the union of the user's visible subtrees (unless they have `budget.manage`)
- [ ] Backend: budget tab access gate = has `budget.manage` OR ≥1 role with a CC assignment
- [ ] CC-scoped `budget.export` exports only the user's visible subtree
- [ ] Frontend admin UI to assign cost-center(s) to a global role
  - [ ] Typeahead / tree-picker for cost-center selection
- [ ] Frontend: budget tab visible in nav when user has visibility; tree shows only permitted subtrees
- [ ] i18n (de + en)

---

## 4. Application detail polish
Target: `frontend/src/app/pages/applications/applications-detail.component.ts`.

- [ ] "Preferred"/empfohlen badge on a position comparison offer (Vergleichsangebot) goes to the **left** of the Value
- [ ] Convert comments into a **chat-style right sidebar** (collapsible, newest at bottom, autoscroll)
  - [ ] Remove the "öffentlich" (public/internal) dropdown — a comment is just a comment
  - [ ] All users who can read the application can see all comments
  - [ ] Backend migration: set existing comments visible to all
  - [ ] Update comment create endpoint to stop accepting/forcing a visibility value
- [ ] Give application values more space to breathe (spacing/layout)
- [ ] i18n (de + en)

---

## 5. /admin/users table fixes
Target: `frontend/src/app/pages/admin/users/users.component.ts`.

- [x] Make the **name** column wider
- [x] Remove the **oidc-subject** column
- [x] Roles column shows **global roles only** (exclude gremium-scoped)
- [x] "Add role" expand view: remove the extra heading (e.g. "Rolle zuweisen: Test User")
- [x] "Assign" button: same height as the date-selectors / dropdown on the left
- [x] "Suchen" button: same height as its input
- [x] i18n if any text changes (de + en)

---

## 6. Webhooks — no global triggers required
Target: `webhooks.component.ts`, `backend/app/modules/admin/models.py` (Webhook), webhook service/router.

- [x] Allow creating a webhook with an empty `events`/triggers list (triggers come from the flow-graph)
- [x] Backend: make events optional / allow empty array; validation no longer requires ≥1 trigger
- [x] Frontend: triggers field optional in create/edit form
- [x] i18n (de + en)

---

## 7. Audit-log overhaul
Human-readable strings built frontend-side via i18n templates per action type.
Target: `frontend/src/app/pages/admin/audit/audit-log.component.ts`, `backend/app/modules/audit/router.py`.

- [ ] Lazy infinite scroll (cursor/keyset pagination on `id` or `at`)
  - [ ] Backend: cursor-based pagination endpoint
  - [ ] Frontend: infinite-scroll list
- [ ] Human-readable rendering
  - [ ] i18n message template per audit action type, filled from entry `data` (de + en)
  - [ ] Enumerate all action types from `backend/app/modules/audit/actions.py`
  - [ ] Fallback rendering for unknown action types
- [ ] Filters: event type, actor, time range
  - [ ] Backend: filter params (action, actor sub, from/to)
  - [ ] Frontend: event-type select, actor picker, date-range picker
- [ ] i18n for filter labels (de + en)

---

## 8. Remove Notifications page (superseded by flow-graph)
Notify is now a flow-graph action. Remove the standalone rules system and the `notification.manage` permission.

- [x] Frontend: remove `notification-rules.component.ts` + spec, route, nav entry
- [x] Backend: remove `backend/app/modules/notifications/` rules CRUD (router/models/service/schemas) — keep only what the flow-graph `notify` action needs (mail send/templating/queue)
- [x] Drop `notification.manage` permission from seeds + frontend permission constants
- [x] Migration to drop notification-rule tables
- [x] Remove related tests
- [x] i18n cleanup (de + en)

---

## 9. Branding & Texts
Target: `branding-editor.component.ts`, `backend/app/modules/admin/branding.py` / `SiteConfigVersion`, `translations.ts` (`footer.coBranding`).

- [ ] Make the co-branding line (currently "A platform of the Student Parliament") editable, per-locale (de + en)
- [ ] Show defaults wherever no value is set / no asset uploaded (placeholders, not blanks)
  - [ ] Logos/wordmark/favicon fall back to defaults
  - [ ] Free-texts fall back to default i18n
- [ ] Wire editable co-branding into footer rendering (replace hardcoded i18n value)
- [ ] i18n (de + en)

---

## 10. Remove Nextcloud export entirely
PDF generation stays (local download); only the Nextcloud upload path leaves.

- [x] Backend: remove `backend/app/modules/pdf/nextcloud.py` and all references in `pdf/service.py`, `pdf/models.py`
- [x] Remove Nextcloud config from `backend/app/settings.py` (credentials/endpoint)
- [x] Remove `backend/tests/test_pdf_nextcloud.py` and any Nextcloud assertions elsewhere
- [x] Remove any frontend buttons/UI referencing Nextcloud export
- [x] i18n cleanup (de + en)

---

## 11. Deprecated-feature cleanup
Decisions recorded. Verify no live references before deleting each; if a live reference is found, stop and ask.

- [ ] **Old voting REST module** (`voting/router.py`, `service.py`, `models.py`, `schemas.py`) — REMOVE (superseded by LiveVote WS); grep live refs first
- [ ] **Old flat budget "pot" model** (`backend/app/modules/budget/models.py` + router/service/schemas) — REMOVE (superseded by hierarchical `tree_models.py`); grep live refs first
- [ ] **Old flow action types** (`setEditLock`, `exportPdf`, `budgetReserve`, `budgetBook`, `openVote`, `requeue` in `flow/dispatch.py:29-35`) — REMOVE dead branches not in `WORKER_ACTION_TYPES`
- [ ] **Webhook global event triggers** — handled in task 6 (make optional, not full removal)
- [ ] **`delegation_voting_enabled` flag** (`settings.py:160`) — KEEP as deployment gate
- [ ] **Deleted docs** (`docs/screenshots/t32/*`, `docs/security/stride-checklist.md`) — already deleted; commit the deletion
- [ ] Remove tests covering removed modules

---

## Cross-cutting reminders
- [ ] New permissions added to admin role + frontend permission constants
- [ ] All new/changed user-facing strings translated in de **and** en
- [ ] Migrations for every schema change (new CC-role table, comment visibility, notification-rule drop, removed voting/pot tables)
- [ ] Tests updated/removed alongside feature changes
