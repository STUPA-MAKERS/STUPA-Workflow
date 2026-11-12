---
id: "000740"
title: The answer list of a Termin names the invited persons without an answer
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - backend/app/modules/calendar/appointments.py
  - frontend/src/app/features/calendar/appointment-detail/appointment-detail.component.html
scope:
  - backend/app/modules/calendar
  - frontend/src/app/features
---

# The answer list of a Termin names the invited persons without an answer

The list "Antworten" of a Termin (000719) must also name each invited person who has not
answered, with the state `Offen` (`Open`). These rows come after the rows with an answer. A
person is invited by name or as a member of an invited Gremium. The same readers see these
rows as see the answers.

Reason: The person who invites must see who still has to answer, not only who answered.

Test: A backend integration test invites two persons, lets one answer and reads the other
as open. A frontend test reads the row with `Offen`.
