---
id: "000728"
title: The desktop Kalender has a week and a month view
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - frontend/src/app/features
---

# The desktop Kalender has a week and a month view

The desktop Kalender must have the segmented control `Woche | Monat` (`Week | Month`). The week
view must show the seven days from Monday to Sunday as columns with an hour axis. A timed entry
must be a block from its start to its end. An all-day entry, an entry over several days and a
due card must be in a row above the hours. The browser must keep the last picked view. The phone
must not show the control.

Reason: Only an hour grid shows which times of a week are free and which entries overlap.

Test: A frontend unit test picks `Woche` and checks that a timed Termin is a block in the column
of its day and that a due card is in the all-day row.
