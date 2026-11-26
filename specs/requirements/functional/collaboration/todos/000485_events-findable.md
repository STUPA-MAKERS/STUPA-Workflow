---
id: "000485"
title: Archived Events stay findable
kind: functional
status: replaced
owner: frederikbeimgraben
updated: 2026-11-25
replaced_by: F/collaboration/events/003033
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/search
---

# Archived Events stay findable

The ⌘K search must have the source `Veranstaltungen`. The source and the board filter
`Veranstaltungen mit Archiv` must include archived Events. An Event in the done column means
that the Event is settled (`abgerechnet`).

Reason: A recurring Event is planned from the data of earlier editions, and these cards are
archived.

Test: A backend unit test finds an archived Event in the search.
