---
id: "003041"
title: Many bookings of an Event fold into one row
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - frontend/src/app/pages/events/event-detail.component.html
scope:
  - frontend/src/app/pages/events
  - frontend/src/app/features/todos
---

# Many bookings of an Event fold into one row

The list `Verknüpft` of an Event must show up to three linked Buchungen as single rows. With four
or more linked Buchungen it must show one row with the number of the Buchungen and their sum,
folded. A press on this row must unfold the Buchungen and a second press must fold them again.
The other kinds of links must stay single rows.

Reason: An Event can have dozens of Buchungen, and they push the Anträge, Bestellungen and cards
out of view. A few Buchungen are easier to read as rows.

Test: A frontend unit test renders an Event with three Buchungen as three rows, and one with four
Buchungen as one folded row that unfolds on a press.
