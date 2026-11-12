---
id: "000750"
title: The two buttons in the tab line of the start page have the same size
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/pages/dashboard/dashboard.component.spec.ts:DashboardComponent"
implementation:
  - frontend/src/app/pages/dashboard/dashboard.component.scss
scope:
  - frontend/src/app/pages/dashboard
---

# The two buttons in the tab line of the start page have the same size

On every width above the phone width, the link of the tab in the tab line of the work list
("Alle Aufgaben öffnen", "Alle Anträge öffnen" and the other links of the tabs) must have the
height, the text size and the side padding of the button "Antrag stellen" (000650) beside it.
The link must be a tonal pill: the surface of `.sheet-back-link` and the normal text colour.
"Antrag stellen" stays the filled button. On the phone, the link stays a small text link above
the list.

Reason: The link was a small text link of 13 px beside a button of 36 px. The two controls in
one line looked like a mistake.

Test: A frontend unit test reads the dashboard stylesheet and finds the height of
"Antrag stellen" on the link in the tab line. Screenshots of the tab line in the light theme,
the dark theme and with very high contrast.
