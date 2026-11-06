---
id: "000441"
title: Antrag and Buchung can name their Event
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - frontend/src/app/features/applications
  - frontend/src/app/features/budget
---

# Antrag and Buchung can name their Event

The detail of an Antrag and the form of a Buchung must have an `Event` picker. The picker
must create or delete the link of the Event card to that element. The picker must list only
Events on boards that the person can write.

Reason: The person who captures an Antrag or a Buchung knows the Event. The link must not
need a second step on the board.

Test: A frontend unit test checks that the picker creates the card link.
