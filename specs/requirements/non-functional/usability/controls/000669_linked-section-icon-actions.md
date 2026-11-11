---
id: "000669"
title: The actions of a "Verknüpft" section are icon buttons
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - frontend/src/app/features/todos/linked-list
  - frontend/src/app/features/todos/card-detail
  - frontend/src/app/pages/tickets
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The actions of a "Verknüpft" section are icon buttons

The head of a section that shows linked to-dos or linked elements must show its actions as
icon buttons: the link icon for "Verknüpfen" and the plus icon for "To-Do anlegen". Each
button must have its text as accessible name. A section must show only the actions that the
view has. This applies also to the section "To-Dos" of a ticket and to the section
"Verknüpft" of a to-do card.

Reason: Antrag, Buchung, Rechnung and Abstimmung use the two icons. The ticket and the card
use text buttons, and two text buttons do not fit beside the title on a phone.

Test: A unit test of the ticket detail and of the card detail expects icon buttons with an
accessible name in the section head and no text button.
