---
id: "000711"
title: The Kalender shows five kinds of entries
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - frontend/src/app/features
---

# The Kalender shows five kinds of entries

The Kalender must show the meetings, the cards with a due date, the Events with a start, the
Termine and the entries of the external calendars. Each kind must follow the read rule of its
own module, so the Kalender never shows an entry that the list of that module does not show. A
done or archived card must not be in the Kalender.

Reason: The Kalender is a second view of data that already has access rules. A separate rule
would let the two views differ.

Test: A backend unit test reads the Kalender as a person without a Gremium and finds no meeting
and no card of a Gremium board.
