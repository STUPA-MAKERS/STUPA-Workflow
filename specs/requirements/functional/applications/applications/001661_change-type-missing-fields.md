---
id: "001661"
title: A change of the Antragsart sends missing required fields to the applicant
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A change of the Antragsart sends missing required fields to the applicant

Before the change of 001660, the dialog must list the required fields of the new form that
have no value. When this list is not empty, the dialog must offer only the manual transitions of
the current state that the person may fire and that lead into a state with `editAllowed`. The
change must fire the chosen transition. Its note must name the missing fields. When the list is
not empty and no such transition exists, the change must not be possible.

Reason: The applicant knows the missing values. The Antrag must go back to the applicant so that the applicant can fill them in.

Test: A backend integration test changes the Antragsart with a missing required field and checks the transition and its note.
