---
id: "000132"
title: An approval can deviate
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/applications/decision.py
  - backend/app/modules/applications/models.py
  - backend/app/modules/flow/mail_actions.py
  - backend/app/modules/budget/tree/applications.py
  - frontend/src/app/pages/applications/decision-dialog/decision-dialog.component.ts
  - frontend/src/app/pages/applications/applications-detail.component.html
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
  - backend/app/modules/budget
  - backend/app/modules/voting
---

# An approval can deviate

A vote proposal can approve an Antrag with a different amount and with conditions. The mail to
the applicant and the Antrag page show the deviation. The budget books only the approved
amount.
The approved amount can be 0 €. It must not be negative.
