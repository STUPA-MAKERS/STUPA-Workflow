---
id: "000132"
title: An approval can deviate
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
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
