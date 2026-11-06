---
id: "000122"
title: An Antrag can be captured on behalf of a person
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# An Antrag can be captured on behalf of a person

A holder of `application.create_on_behalf` must be able to capture an Antrag for an existing
account or for a guest with name and e-mail. The Antrag must belong to the applicant. The
capture dialog must follow the pattern of "Buchung hinzufügen".
