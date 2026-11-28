---
id: "003082"
title: Each part of the pretix integration has its own switch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/pretix/connection.py
  - frontend/src/app/pages/admin/pretix
scope:
  - backend/app/
  - frontend/src/app/
---
# Each part of the pretix integration has its own switch

The admin page `Pretix` must have one switch for each of these parts: `Verkaufszahlen zeigen`
(003084) and `Einnahmen buchen` (003086). Each switch must start
off. While a switch is off or the connection has no token, the platform must not call pretix for
that part and must not show an element of it. The link of an Event to a pretix event (003083)
must need only the connection.

Reason: An integration has a switch per part (000176). An admin can show the sales and keep the
bookings by hand.

Test: A backend unit test runs the refresh of 003085 with `Verkaufszahlen zeigen` off and
expects no call to pretix.
