---
name: budget-kostenstellen-spec
description: How hierarchical budgets and cost centers (Kostenstellen) must work in the antragsplattform (per the SRS)
metadata: 
  node_type: memory
  type: reference
---

Budget model the user wants, per the SRS. The spec lives in the project **wiki**. Read the exact
spec there before you build.

- **Top level = Budget** (for example "VS-Mittel", key `VS`).
- Below it, **cost centers (Kostenstellen, KS) nest to any depth**: for example "Dezentrale
  Einrichtungen" key `800` → "Fachschaft Informatik" key `40`.
- The **full name of a cost center concatenates the key path**, for example
  `VS-800-40 – Fachschaft Informatik`.
- **Available budget rolls DOWN** the tree. **Consumed budget rolls UP**: when an application is
  assigned to a cost center, its amount aggregates upward.

**Correction (2026-06-08): budgets are NOT tied to a Gremium.** A top-level budget needs no
Gremium. The backend `create_node` makes `gremiumId` optional. "Above amount X, Gremium Y must
vote" is a FLOW rule: an amount-threshold guard fires a gremium-scoped vote action. It is not a
budget-to-Gremium binding (#23). **Fiscal years are created INSIDE a budget**, one set per
top-level budget, never through a global dropdown. So the budget-tree editor must be budget-scoped
(#22).

Backend state (checked 2026-06-08): migration **0020_budget_hierarchy** already added the schema.
It holds the `budget` table (a self-FK tree plus `path_key`), `fiscal_year`, the application
columns for cost center and fiscal year, and the roll-up SQL over the `path_key` prefix
(`leaf.path_key LIKE b.path_key || '-%'`). BUT `modules/budget/router.py` exposes only the **flat**
`/budget-pots` CRUD, `/budget/stats` and assign. There is **no REST API for the tree yet**. So this
is full-stack work: add a tree CRUD service and router on the existing `budget` model, then add a
frontend tree editor that replaces the cluttered flat `pages/budget/budget-pots`. The entry stages
are `requested/reserved/approved/paid`. See [[antragsplattform-backlog]].
