---
name: budget-tab-redesign
description: "Spec for the Budget-tab redesign: left Budget-to-Year tree, stacked pie charts, requested column, cost-center colors, state-based roll-up, URL sync, admin reuse"
metadata: 
  node_type: memory
  type: project
---

Budget-tab redesign on branch feat/admin-ux-flow-editor-fixes (2026-06-09). The user confirmed
every decision with the question tool. The "Budget" nav tab is `/budget` and renders
budget-dashboard.component (templateUrl and .scss). The admin page is `/admin/budget-pots` and
renders budget-tree.component. The budget tree data comes from `BudgetTreeApi`
(budget-tree.api.ts): `tree()` calls GET /budgets and returns BudgetTreeNode[], nested, with
byFiscalYear[{fiscalYearId,allocated,committed,available}] and children. The backend tree math
lives in budget/tree_service.py and tree_rules.py. Budget is a critical module, so its tests need
100% branch coverage.

## Confirmed decisions
- **Requested column plus accepted and denied states (STATE-BASED REPLACES STAGE-BASED):** a
  top-level Budget stores `accepted_state_keys` and `denied_state_keys` (flow state keys),
  configured in admin/budget-pots. Per node, subtree and fiscal year: `committed` (UI label
  Gebunden) is the summed amount of the assigned applications whose current state.key is in
  accepted, plus the direct BudgetExpense rows. `requested` (UI label Beantragt) is the summed
  amount of the applications that are neither accepted nor denied, so the in-flight ones. Denied
  applications drop out. `available` = allocated − committed. This REPLACES the BudgetEntry-stage
  roll-up for the budget views. The byFiscalYear payload gains `requested`.
- **Pie charts:** TWO charts stacked vertically in a RIGHT sidebar. Chart 1 shows allocated per
  direct sub-center. Chart 2 shows committed and requested per direct sub-center. Both include the
  un-suballocated remainder of the parent as a slice. Each slice takes the node color. On hover a
  slice highlights and grows radially, with animation and a tooltip. Each chart carries a short
  title ABOVE it. Draw NO box around a chart.
- **Colors:** add a `color` column to the budget node (nullable, backend migration). Put a color
  picker in the admin budget editor. The color drives the pie slices and the left-tree dots.
- **Left sidebar (dashboard and admin):** a Budget-to-Year tree with 2 levels, a top Budget over
  its fiscal years. A click selects the budget and the year. The current entry is highlighted.
  Style: **dotted light-green lines, compact**. Show "…" when a budget has more than 5 years. This
  replaces the Budget and Year dropdowns. The cost-center drilldown stays in the MAIN area. Build
  it as a SHARED component that the dashboard AND admin/budget-pots both use.
- **Admin /admin/budget-pots:** rebuild it around the SAME layout: a left Budget-to-Year tree plus
  a main editor for create, rename and allocate, the colors, and the accepted and denied state
  config per top budget.
- **Breadcrumbs:** omit them at the top level. When the selected cost center is the top budget,
  show no breadcrumb.
- **URL sync:** keep the selected cost center, budget and year in the query params, so the view
  stays shareable and linkable.

## Build slices (sequential commits)
1. Backend: budget `color` column plus top-budget `accepted_state_keys` and `denied_state_keys`
   (JSONB), a migration, and the schemas (BudgetNodeOut, Create and Update).
2. Backend: the state-based roll-up in tree_service and tree_rules, where committed counts the
   accepted applications and the expenses, and requested counts the in-flight ones. Add
   byFiscalYear.requested. Update the budget tests.
3. Frontend: the shared left Budget-to-Year tree component (dotted light-green, compact, and "…"
   for more than 5 years) and the shared interactive pie-chart component (SVG, hover grow and
   highlight, tooltip).
4. Frontend: dashboard redesign with the left tree, the main area plus the Requested column, the
   right stacked pies, URL sync, and the breadcrumb omission.
5. Frontend: admin/budget-pots redesign with the left tree, the editor, the color picker and the
   accepted and denied state multiselect.
6. i18n de and en, plus the specs.

**STATUS — DONE (2026-06-09), 5 commits pushed.** Backend: budget `color` plus per-top
`accepted_state_keys` and `denied_state_keys` (migration 0041), and the state-based committed and
requested roll-up. `tree_rules.build_forest` takes requested_rows. `tree_service.get_tree` joins
Application to State and classifies per top config. Frontend: the shared
`budget-year-tree.component.ts` (left nav) and `budget-pie.component.ts` (interactive donut, with
PALETTE fallback colors). The dashboard is rebuilt with a 3-zone layout, the Requested column, the
breadcrumb omission at the top level, and URL sync through the query params budget, ks and fy. The
admin page /admin/budget-pots is rebuilt with the left tree, the color picker and the accepted and
denied state matrix. It loads the global flow states through AdminApiService.getGlobalFlow.
budget-tree.api.ts gained the color, requested and state fields, BudgetNodeUpdate and
flattenBudgetOptions. All 40 budget frontend specs and 143 budget backend tests are green. The
frontend build is clean.

**Caveats:** pie chart 2 shows committed only, not committed plus requested. The mock interceptor
does NOT serve /budgets, so the dev and demo modes show empty budget pages. The real Docker backend
works. The integration budget tests moved to state-based, but they are DB-gated, so only CI
verifies them. The user must run migration 0041.

See [[budget-kostenstellen-spec]] and [[flow-engine-redesign]]. Work autonomously
[[work-autonomously]]. Write the i18n strings in both de and en [[admin-domain-rules]]. Keep the UI
like Nextcloud [[nextcloud-parity-ui]].
