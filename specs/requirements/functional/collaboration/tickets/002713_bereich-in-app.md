---
id: "002713"
title: A Bereich can take tickets from signed-in persons
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_waiting.py:test_a_report_without_a_session_reaches_plattform_only"
  - "backend/tests/unit/modules/tickets/test_ticket_waiting.py:test_a_report_reaches_a_bereich_with_the_switch_only"
  - "backend/tests/unit/modules/tickets/test_ticket_waiting.py:test_the_choices_are_plattform_and_the_bereiche_with_the_switch"
  - "frontend/src/app/features/help/report-dialog/report-dialog.component.spec.ts:ReportDialogComponent"
implementation:
  - backend/app/modules/tickets/service/create.py
  - backend/app/modules/tickets/areas.py
  - backend/app/modules/tickets/router.py
  - frontend/src/app/features/help/report-dialog/report-dialog.component.ts
  - frontend/src/app/pages/admin/help-tickets/ticket-area-dialog.component.ts
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A Bereich can take tickets from signed-in persons

A Bereich must have the switch `In der App erreichbar`. While the switch is on, a signed-in
person must be able to choose the Bereich in the ticket dialog of the help menu. A person
without a session must reach only the Bereich `Plattform` (000150).

Reason: A member asks a Gremium a question without a mail. A public form for each Bereich would
open each team to spam.

Test: A unit test sends a ticket without a session to a Bereich with the switch on and expects
403.
