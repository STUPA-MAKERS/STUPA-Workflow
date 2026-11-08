---
id: "000549"
title: A due card of a person is in their calendar
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-08
implementation: null
scope:
  - backend/app/modules/todos
  - backend/app/modules/calendar
---

# A due card of a person is in their calendar

A card with a due date must be an all-day entry on that date in the calendar feed of each
assigned person who can read its board. The entry must show the title of the card and the name
of its board and must link to the card. A done or archived card must not be in the feed.

Reason: The members see their deadlines beside the meetings and the Events.

Test: A backend unit test reads a due card from the feed and does not find it after it is done.
