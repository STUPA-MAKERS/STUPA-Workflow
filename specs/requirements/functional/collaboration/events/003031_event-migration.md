---
id: "003031"
title: The migration makes an Event of each event card
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/migrations/versions/7c4e2a9d1b85_events.py
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# The migration makes an Event of each event card

A data migration must make an Event of each card with event data. The Event must get the title,
the description, the dates, the times, the place, the participants and the series of the card,
the creator and the date of creation of the card, and the team of the board of the card (003067). A card on a board without a team (a free
board) must take the one team entry of the board with the role edit or manage. A board with no
such entry or with more than one must get a new team with the name of the board: each person
entry of the board becomes a member, an entry with manage becomes a manager, and without a
manager the person entries with manage, else the creator of the card, become managers. The new
team must get its own board (003067). The status must be `settled` (003039) for a card in the done column
of its board or in the archive, else `planned`. Each link of the card must also become a link of
the Event. The card must stay on its board with its checklist, comments, assignees, labels and
links, lose its event data, and get a link to the new Event. A link of another element to the
card must stay.

Reason: The Events of the boards must not be lost. The checklist and the comments are the work
on the Event, and this work stays a to-do on the board.

Test: A migration test makes an Event of a card in the done column with a link and a series,
and finds the status `settled`, the series, the link at the Event and the card with a link to
the Event.
