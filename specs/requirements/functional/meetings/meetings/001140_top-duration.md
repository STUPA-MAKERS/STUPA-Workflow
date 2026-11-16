---
id: "001140"
title: A TOP carries an estimated duration
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
implementation:
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - mcp
---

# A TOP carries an estimated duration

Each TOP of a Sitzung must take an optional estimated duration in whole minutes, from 1 to 480.
The dialogs "TOP hinzufügen" and "TOP bearbeiten" must show the number field "Dauer (Min.)" for
every kind of TOP. Only a person who may change the agenda must set or clear the duration. An
empty field must clear it. The MCP tools that add or change a TOP must take the duration too.

Reason: Ticket T-0019 asks for an estimate per TOP ("z.B. 10 min"), so that the agenda can
compute a time plan (001141).

Test: Unit test of the agenda service: a value outside 1 to 480 is refused, and an empty value
clears the duration. Component test of the dialog: the field is shown for each kind.
