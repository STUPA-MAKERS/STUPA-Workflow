---
name: budget-tab-redesign
description: "Spec for the Budget-tab redesign — left Budget→Year tree, stacked pie charts, beantragt column, cost-centre colors, state-based rollup, URL sync, admin reuse"
metadata: 
  node_type: memory
  type: project
---

Budget-tab redesign on branch feat/admin-ux-flow-editor-fixes (2026-06-09). All decisions confirmed via question tool. "Budget" nav tab = `/budget` = budget-dashboard.component (templateUrl/.scss). Admin = `/admin/budget-pots` = budget-tree.component. Budget tree data via `BudgetTreeApi` (budget-tree.api.ts): `tree()` GET /budgets → BudgetTreeNode[] (nested, byFiscalYear[{fiscalYearId,allocated,committed,available}], children). Backend tree math in budget/tree_service.py + tree_rules.py (budget = critical module, 100% branch coverage tests).

## Confirmed decisions
- **Beantragt column + accepted/denied states (STATE-BASED REPLACES STAGE-BASED):** a top-level Budget stores `accepted_state_keys` + `denied_state_keys` (flow state keys), configured in admin/budget-pots. Per node+subtree+fiscal-year: `committed`(Gebunden) = Σ amount of assigned applications whose current state.key ∈ accepted (+ direct BudgetExpense); `requested`(Beantragt) = Σ of those neither accepted nor denied (in-flight); denied excluded; `available` = allocated − committed. This REPLACES the BudgetEntry-stage rollup for budget views. byFiscalYear payload gains `requested`.
- **Pie charts:** TWO stacked vertically in a RIGHT sidebar — chart 1 = allocated per direct sub-center, chart 2 = committed/beantragt per direct sub-center. Include the parent's own un-suballocated remainder as a slice. Colored by node color. Interactive: hover → highlight + radial grow, animated; tooltip. Short title ABOVE each. NO box around.
- **Colors:** add `color` column to budget node (nullable, backend migration). Color picker in the admin budget editor. Used for pie slices + left-tree dots.
- **Left sidebar (both dashboard + admin):** Budget→Year tree, 2 levels (top Budget → its fiscal Years), clickable (selects budget+year), current highlighted, **dotted light-green lines, compact**. Shows "…" when a budget has >5 years. Replaces the Budget + Year dropdowns. Kostenstelle drilldown stays in the MAIN area. Build as a SHARED component used by dashboard AND admin/budget-pots.
- **Admin /admin/budget-pots:** rebuild around the SAME layout — left Budget→Year tree + main editor (create/rename/allocate + colors + accepted/denied-state config per top budget).
- **Breadcrumbs:** omit at top level (when selected Kostenstelle == top budget, no breadcrumb).
- **URL sync:** selected cost centre (+ budget/year) in query params → shareable/linkable.

## Build slices (sequential commits)
1. Backend: budget `color` column + top-budget `accepted_state_keys`/`denied_state_keys` (JSONB) + migration + schemas (BudgetNodeOut/Create/Update).
2. Backend: state-based rollup (committed=accepted apps+expenses, requested=in-flight) in tree_service/tree_rules; byFiscalYear.requested. Update budget tests.
3. Frontend: shared left Budget→Year tree component (dotted light-green, compact, …>5) + shared interactive pie-chart component (SVG, hover grow+highlight, tooltip).
4. Frontend: dashboard redesign — left tree, main + Beantragt col, right stacked pies, URL sync, breadcrumb omit.
5. Frontend: admin/budget-pots redesign — left tree + editor + color picker + accepted/denied-state multiselect.
6. i18n de/en + specs.

**STATUS — DONE (2026-06-09), 5 commits pushed.** Backend: budget `color` + per-top `accepted/denied_state_keys` (migration 0041) + state-based committed/requested rollup (tree_rules.build_forest takes requested_rows; tree_service.get_tree joins Application→State + classifies per top config). Frontend: shared `budget-year-tree.component.ts` (left nav) + `budget-pie.component.ts` (interactive donut, PALETTE fallback colors) + dashboard rebuilt (3-zone layout, beantragt col, breadcrumb omit at top, URL sync via query params budget/ks/fy) + admin /admin/budget-pots rebuilt (left tree + color picker + accepted/denied state matrix, loads global flow states via AdminApiService.getGlobalFlow). budget-tree.api.ts gained color/requested/state fields + BudgetNodeUpdate + flattenBudgetOptions. All 40 budget FE specs + 143 budget BE tests green; FE build clean.

**Caveats:** pie chart 2 = committed only (not committed+requested). Mock interceptor does NOT serve /budgets (dev/demo mode shows empty budget pages; real Docker backend fine). Integration budget tests updated to state-based but DB-gated → CI-verified. User must run migration 0041.

See [[budget-kostenstellen-spec]], [[flow-engine-redesign]]. Work autonomously [[work-autonomously]]; i18n de+en both [[admin-domain-rules]]; UI like Nextcloud [[nextcloud-parity-ui]].
