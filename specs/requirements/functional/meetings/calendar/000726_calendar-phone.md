---
id: "000726"
title: The Kalender on the phone is a list of days
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - frontend/src/app/features
---

# The Kalender on the phone is a list of days

A phone must show the Kalender as a list of the days with entries, from today on, and must load
earlier and later days at the ends of the list. A desktop must show the month grid with the side
panel of the picked day. An entry over several days must be one bar across its days in the grid
and one row at each of its days in the list.

Reason: A month grid on a phone has cells too small to read or to press.

Test: A frontend unit test renders a three-day Termin as one bar in the grid and as three rows
in the list.
