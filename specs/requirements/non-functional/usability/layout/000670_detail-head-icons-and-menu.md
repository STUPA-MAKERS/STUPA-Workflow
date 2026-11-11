---
id: "000670"
title: A detail head has icon buttons and a menu
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - frontend/src/app/pages/budget
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A detail head has icon buttons and a menu

On a wide screen the head of a detail pane must show its actions as icon buttons and must put
the other actions in the ⋮ menu. A button with a count plate (000604) keeps its text. The
budget detail must show the export as an icon button and "Buchungen ansehen" in the ⋮ menu.

Reason: Antrag, Buchung, Rechnung and Ticket have icon buttons and the menu. The budget
detail has two text buttons and no menu.

Test: A unit test of the budget detail expects one icon button for the export, a ⋮ menu with
the entry "Buchungen ansehen" and no text button in the head.
