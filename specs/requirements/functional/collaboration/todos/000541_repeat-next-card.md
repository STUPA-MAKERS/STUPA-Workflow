---
id: "000541"
title: Done on a repeating to-do creates the next one
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-07
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# Done on a repeating to-do creates the next one

A move of a repeating card into the done column must create the next card in the first column
of the same board. The next card must get the title, the description, the labels, the
assignees, the repeat rule and the checklist with all items open. Its due date must be the old
due date plus the interval, stepped forward until it is after today. The next card must not
get links, comments or the history. The done card must lose its repeat rule, so that a move
out of the done column and back creates no second card.

Reason: The interval counts from the due date and not from the day of completion, so a late duty does not move the schedule. The rule lives on one card only, so there is never more than one open card of a series.

Test: A backend unit test moves a repeating card to done twice and finds exactly one next card.
