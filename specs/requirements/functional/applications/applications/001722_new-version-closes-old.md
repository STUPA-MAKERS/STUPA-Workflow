---
id: "001722"
title: Submitting the new version closes the old Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# Submitting the new version closes the old Antrag

When the applicant submits the new version (001720), the old Antrag must move into the state
that the flow marks as `Ziel für ersetzte Anträge` (`Target for replaced Anträge`), when the old
Antrag is not yet in a terminal state. This state must be terminal and must have the flag
`Abgelehnt`. The status event must have the note `Ersetzt durch <number>`
(`Replaced by <number>`). Open votes of the old Antrag must be cancelled (000235). When the flow
has no such state, the old Antrag must stay as it is.

Reason: Prod data holds 4 second versions where the old Antrag stayed open or was denied by hand. An open old Antrag also counts its requested amount in the budget (000572).

Test: A backend integration test submits a new version and checks the state and the note of the old Antrag.
