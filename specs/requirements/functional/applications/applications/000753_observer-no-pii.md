---
id: "000753"
title: An observer does not see personal fields
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
implementation:
  - backend/app/modules/applications
scope:
  - backend/app/modules/applications
  - frontend/src/app/features/apply
  - frontend/src/app/pages/applications
---

# An observer does not see personal fields

The observer view must not show the answers of fields with `is_pii` and must not show the
applicant record. The observer view must show the name of the applicant only as the line
"Eingereicht von <Name>".

Reason: An observer needs the progress of the Antrag, not the bank details or the address of the
applicant.

Test: `backend/tests/integration/modules/applications/test_observers.py`: the observer read has
no `is_pii` answer and no applicant e-mail.
