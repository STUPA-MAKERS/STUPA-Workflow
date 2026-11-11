---
id: "000737"
title: The Kalender shows an Event like a Termin
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - frontend/src/app/features
---

# The Kalender shows an Event like a Termin

The Kalender must show an Event in the same form as a Termin: a timed Event as a block at its
time in the week view, an all-day Event and an Event of more than one day as a bar. The filter
by kind must count an Event to the kind `Termin`, and the Kalender must have no kind
`Veranstaltung`. A press on an Event must open its card.

Reason: For the person who reads the Kalender an Event is a date like each other date. The card
stays the one place for its data.

Test: A frontend unit test renders an Event with a time in the week view and finds it as a block
at that time, then sets the filter to `Termin` and still finds it.
