---
id: "001272"
title: The activity page reuses the read gate of each module
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-17
implementation:
  - backend/app/modules/activity
  - frontend/src/app/pages/activity
scope:
  - backend/app/modules/activity
  - frontend/src/app/pages/activity
---

# The activity page reuses the read gate of each module

The activity page must not have a gate of its own. Each source must show an event only when the
read rule of its module lets the person read the item, with the same scope as the module route.
An event must show only what the detail page of the item shows to the person: an internal
comment only to a reader of internal comments, a team note of a ticket only to a holder of
`ticket.manage`. When the person loses the read right, the events of the item must leave the
page.

Reason: A permission change in a module then reaches the activity page by itself, the same as
for the search (000328).
