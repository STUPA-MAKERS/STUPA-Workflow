---
id: "000876"
title: A plan on the agenda is an Anlage of the protocol
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/livevote/test_plan_agenda_vote.py:test_a_draft_is_an_agenda_item_for_a_reading"
  - "backend/tests/integration/modules/livevote/test_plan_agenda_vote.py:test_the_protocol_appends_the_plans_of_its_agenda"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_open_of_a_vote_keeps_the_file_of_the_plan"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_reader_gets_the_drafts_for_a_reading"
  - "frontend/src/app/features/meetings/agenda-item-dialog/agenda-item-dialog.component.spec.ts:AgendaItemDialogComponent"
implementation:
  - backend/app/modules/budget/tree/plan_exports.py
  - backend/app/modules/budget/plan_models.py
  - backend/app/modules/protocol/plan_anlage.py
  - backend/app/modules/livevote/router.py
  - backend/app/modules/meetings/agenda_service.py
  - frontend/src/app/features/meetings/agenda-item-dialog/agenda-item-dialog.component.ts
scope:
  - backend/app/modules/budget
  - backend/app/modules/livevote
  - backend/app/modules/meetings
  - backend/app/modules/protocol
  - backend/app/modules/voting
  - frontend/src/app/features/meetings
---

# A plan on the agenda is an Anlage of the protocol

A draft of a Haushaltsplan can be a TOP of a meeting for a reading, without a request
for a decision. The meeting must be one of a Gremium that decides the plan of the
Haushalt in a step (000826). The person who edits the agenda picks the draft from the
drafts of these Haushalte that this person can read. Such a TOP has no motion and no
vote, and the version stays a draft. A plan is at most one TOP of a meeting (000838).

The dialog "TOP hinzufügen" must list the plans under their own kind "Haushaltsplan",
beside "Antrag", "To-Do" and "Freitext": the versions that wait for the decision of the
Gremium, and the drafts for a reading. The kind must show only in a meeting of a Gremium
that decides the plan of a Haushalt in a step.

The protocol of a meeting must append the PDF (000875) of each plan on its agenda as an
Anlage (000864) and must reference it in the TOP of the plan:

- a plan for a reading: the version as it is when the protocol is finalized;
- a plan with a vote (000838): the version as it is when the vote opens. A later change
  or the delete of the draft, after a refused vote, must not change the Anlage.

The public protocol holds the Anlage only when the TOP is public (000867).

Reason: The protocol is the record of the meeting. For a decision it must show the plan
that the Gremium decided on. For a reading it shows the result of the reading.

Test: Integration tests: a draft is a TOP without a vote, changes before the protocol is
finalized, and the Anlage holds the changed amounts. A plan is voted on and refused, the
draft changes, and the Anlage holds the amounts of the vote. A meeting of another Gremium
does not get the draft. Component test: the kind "Haushaltsplan" lists the plans and is
absent in a Gremium that decides no plan.
