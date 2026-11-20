---
id: "001621"
title: The timeline and the audit show the old and the new approved amount
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/applications/amend_mail.py
  - backend/app/modules/applications/service/reads.py
  - frontend/src/app/shared/decision/timeline-lines.ts
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The timeline and the audit show the old and the new approved amount

A change of the approved amount (001620) must add a timeline entry
`Genehmigter Betrag geändert` (`Approved amount changed`) with the old amount, the new amount,
the reason, and the date and the Gremium of the decision. It must write an
`application_decision` audit entry with the old and the new amount. The applicant must get a
mail with the old and the new amount.

Reason: The change of an approved amount changes the money of the applicant and of the budget, so every reader must see it.

Test: A backend unit test checks the timeline entry, the audit entry and the mail.
