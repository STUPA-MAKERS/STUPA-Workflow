---
id: "000742"
title: The invitation search of a Termin shows its hits as rows with an avatar
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
implementation:
  - frontend/src/app/features/calendar/appointment-dialog/appointment-dialog.component.html
scope:
  - frontend/src/app/features
---

# The invitation search of a Termin shows its hits as rows with an avatar

The field "Person einladen" of the Termin dialog must be the search field of the other person
searches of the app: a search pill, and below it one row per hit with the avatar and the name
of the person. A press on a row invites the person.

Reason: A person search that looks different in one dialog reads as a different function, and
a hit without an avatar does not read as a person.

Test: A frontend test types a name, reads the list of hits and invites a person with a press
on a row.
