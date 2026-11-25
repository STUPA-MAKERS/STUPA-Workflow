---
id: "003025"
title: An Event has a status of its status list
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/events/models.py
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# An Event has a status of its status list

The status of an Event must be one status of the list of the Events (003035). A new Event must
get the start status of the list. A person who writes the Event can set each status from each
status. The code must read only the phase of the status (003036).

Reason: Today an Event in the done column of its board counts as settled (000485). The phase
`done` keeps this meaning without a board, and each student government names its own steps.

Test: A backend unit test adds a status to the list of the Events, sets an Event to it and back.
