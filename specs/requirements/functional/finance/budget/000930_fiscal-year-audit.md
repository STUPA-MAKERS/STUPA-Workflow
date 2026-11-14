---
id: "000930"
title: The create and the change of a fiscal year are in the audit log
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_fiscal_year_writes_its_audit_entries"
  - "frontend/src/app/pages/admin/audit/audit-log.component.spec.ts:AuditLogComponent"
implementation:
  - backend/app/modules/budget/tree/fiscal_years.py
  - backend/app/modules/audit/actions.py
  - frontend/src/app/pages/admin/audit/audit-log.component.ts
scope:
  - backend/app/modules/budget
  - backend/app/modules/audit
  - frontend/src/app/pages/admin/audit
---

# The create and the change of a fiscal year are in the audit log

The create of a fiscal year must write the audit entry `budget_fiscal_year_create`, and a
change of its year or of its active flag the entry `budget_fiscal_year_update`. Each entry
must hold the Haushalt, the year and the active flag, and the entry of a change also the
two values before it. The audit page must name both actions and offer them in its filter.

Reason: The fiscal year sets where a booking and an Ansatz belong. The delete, the close
and the reopen of a year are in the audit log (000255, 000802), so a year that appears or
changes its number without an entry is a gap in the record of the money.

Test: The integration test creates a fiscal year, changes its year and then its active
flag, and reads the three entries with their values. The test of the audit page reads the
two actions in the filter.
