---
id: "000597"
title: A section in a detail and a small tile show one ghost row
kind: non-functional
status: replaced
owner: frederikbeimgraben
updated: 2026-11-19
replaced_by: NF/usability/controls/001360
scope:
  - frontend/src/app/
---

# A section in a detail and a small tile show one ghost row

An empty list must show one ghost row (`rows="1"`) when it is a section of a detail or a small
tile. All other empty lists keep their ghost rows (000205, 000412).

- Section of a detail: a section head with an action, and the empty list below it. Examples:
  Antrag "Anhänge" and "Verlauf", "Unterbuchungen", Rechnung "Buchungen", the Kostenstelle
  lists, "Verknüpft" and the linked to-dos (000582), Ticket "Duplikat", webhook deliveries, the
  actions and transitions of the flow editor, an empty form group, the version history and the
  attendance of one meeting.
- Small tile: "Keine kommenden Sitzungen" and the calendar subscription in the account.
- Unchanged: dialogs, sheets and pickers keep their rows, so the dialog height does not jump
  while the user types. Main lists and tabs keep 3 or 5 rows, because they fill the page. The
  chat and the protocol text keep their own shapes.

Reason: A detail has many sections and a tile is small. One row says "empty" and keeps the
detail short.

Test: Review of the `rows` input of each `app-empty-state` in the files above.
