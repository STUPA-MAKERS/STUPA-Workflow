---
id: "003022"
title: An Event is an element of its own
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/events/models.py
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# An Event is an element of its own

An Event (`Veranstaltung`) must be an element of its own in the table `event` with its own page
(003027), and must not be a card of a board. A card must not carry event data. The dialog of a new
card must not have the switch `To-Do | Veranstaltung`, and the menu of a card must not have
`Zur Veranstaltung umwandeln`. A card can link an Event like each other element (003033). Each
new Event must get the number `V-` followed by eight random characters, like a Bestellung
(002855). The German UI calls an Event `Veranstaltung`, the English UI calls it `Event`.

Reason: An Event has a date, a place, money and decisions, and it lives longer than the work on
a board. On a board it hides between the to-dos, and it is hard to find. As an element of its own it
is easy to find, like a Bestellung. It gets its rights from its team (003026).

Test: A backend unit test creates an Event and reads its number. A backend unit test gets 422 for
a new card with event data.
