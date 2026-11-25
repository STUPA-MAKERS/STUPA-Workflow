---
id: "003031"
title: The migration makes an Event of each event card
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/alembic/versions
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# The migration makes an Event of each event card

A data migration must make an Event of each card with event data. The Event must get the title,
the description, the dates, the times, the place, the participants and the series of the card,
the creator and the date of creation of the card, and the board of the card. The status must be `settled` (003039) for a card in the done column
of its board or in the archive, else `planned`. Each link of the card must also become a link of
the Event. The card must stay on its board with its checklist, comments, assignees, labels and
links, lose its event data, and get a link to the new Event. A link of another element to the
card must stay.

Reason: The Events of the boards must not be lost. The checklist and the comments are the work
on the Event, and this work stays a to-do on the board.

Test: A migration test makes an Event of a card in the done column with a link and a series,
and finds the status `settled`, the series, the link at the Event and the card with a link to
the Event.
