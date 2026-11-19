---
id: "001403"
title: The card links move to the new table
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/migrations/versions
scope:
  - backend/app/modules/links
  - backend/app/modules/todos
---

# The card links move to the new table

The migration must copy each row of `todo_link` into `link`, with the card as one end and the
target as the other end. Two rows that link the same two cards in both directions must become
one link. The migration must keep `created_by` and `created_at`. The migration must then drop
`todo_link`. The ticket coupling (`completeTodos`), the agenda item of a card, the card events
`link_added` and `link_removed`, the account merge, the privacy export and the board read must
read `link`.

Reason: Two tables for the same relation would show different links on the two ends.

Test: A migration test fills `todo_link` with one row of each kind and two opposite card rows,
runs the upgrade and counts the rows in `link`.
