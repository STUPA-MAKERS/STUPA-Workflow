---
id: "000497"
title: A user can report a barrier as a ticket
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/src/app/features/help/report-dialog/report-dialog.component.spec.ts:ReportDialogComponent"
  - "frontend/src/app/features/accessibility/accessibility-statement.component.spec.ts:AccessibilityStatementComponent"
  - "backend/tests/unit/modules/tickets/test_ticket_router.py:test_an_anonymous_barrier_report_passes_while_public_reports_are_off"
implementation:
  - frontend/src/app/features/help/report-dialog/report-dialog.component.ts
  - frontend/src/app/features/help/help.service.ts
  - backend/app/modules/tickets/router.py
  - backend/app/modules/tickets/models.py
  - backend/migrations/versions/db31a12f701e_ticket_kind_barrier.py
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - backend/app/modules/tickets
---

# A user can report a barrier as a ticket

The help ticket form must have the kind `barrier`. The form must work without a login. The
statement page must link to this form.

Reason: The law requires a feedback route. The help tickets already give one, so a new
channel is not necessary.
