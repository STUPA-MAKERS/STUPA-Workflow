---
id: "001771"
title: The desktop Kalender has no visible title and its buttons end the tools row
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/features/calendar/calendar.component.html
  - frontend/src/app/features/calendar/calendar.component.scss
scope:
  - frontend/src/app/features/calendar
---

# The desktop Kalender has no visible title and its buttons end the tools row

On every width above the phone width, the Kalender must not show its title; the title stays in
the page for a screen reader. The button "Kalender-Abo" and the button "Termin anlegen" must
form one button group (001350) at the right end of the row with the month navigation, "Heute"
and `Woche | Monat`. The search and the filters must be in a row of their own below it. The page
must not show a FAB on these widths. On the phone the title line and the FAB stay. The public
Kalender must show only its button "Abonnieren" in that group.

Reason: The title repeated the name of the active item of the navigation (001500), and the FAB
lay over the grid and covered the days of the last week. The tools row has room for the
buttons of the page.

Test: A frontend unit test finds the button in the tools row on the desktop and no FAB.
