---
name: budget-kostenstellen-spec
description: How hierarchical budgets / Kostenstellen must work in the antragsplattform (per SRS / project wiki)
metadata: 
  node_type: memory
  type: reference
---

Budget model the user wants (per SRS, spec lives in the project **wiki** — get the exact spec there before building):

- **Top level = Budget** (e.g. "VS-Mittel", key `VS`).
- Below it, **arbitrarily nested Kostenstellen (KS)**: e.g. "Dezentrale Einrichtungen" key `800` → "Fachschaft Informatik" key `40`.
- A KS's **full name concatenates the key path**: `VS-800-40 – Fachschaft Informatik`.
- **Available budget rolls DOWN** the tree; **consumed budget rolls UP** (when applications/Anträge are assigned to a KS, their amounts aggregate upward).

**Correction (2026-06-08): budgets are NOT tied to a Gremium.** A top-level budget has no required gremium (backend `create_node` makes `gremiumId` optional). "Above amount X, gremium Y must vote" is a FLOW rule (amount-threshold guard → gremium-scoped vote action), not a budget↔gremium binding (#23). **Fiscal years are created INSIDE a budget** (per top-level), never via a global dropdown — the budget-tree editor must be budget-scoped (#22).

Backend state (checked 2026-06-08): migration **0020_budget_hierarchy** already added the schema — `budget` table (self-FK tree + `path_key`), `fiscal_year`, application→KS/HHJ columns, and roll-up SQL via `path_key` prefix (`leaf.path_key LIKE b.path_key || '-%'`). BUT `modules/budget/router.py` only exposes the **flat** `/budget-pots` CRUD + `/budget/stats` + assign — there is **no REST API for the tree yet**. So this is full-stack: add tree CRUD service+router on the existing `budget` model, then a FE tree editor replacing the cluttered flat `pages/budget/budget-pots`. Entry stages: `requested/reserved/approved/paid`. See [[antragsplattform-backlog]].
