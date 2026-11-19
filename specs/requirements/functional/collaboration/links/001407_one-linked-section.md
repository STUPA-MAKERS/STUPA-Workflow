---
id: "001407"
title: Each element shows all its links in Verknüpft
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/features/todos
scope:
  - frontend/src/app/features/todos
  - frontend/src/app/pages
  - frontend/src/app/features/meetings
  - frontend/src/app/features/voting
  - frontend/src/app/features/calendar
  - frontend/src/app/features/gremien
---

# Each element shows all its links in Verknüpft

The detail of each kind of F/collaboration/links/001400 must have the section `Verknüpft`
(`Linked`). The section must show every link of the element in one list. Each row must show the
icon of its kind, the kind and the title. A linked Event must be the first row. The other rows
must be in the order of the kinds in 001400, and in each kind the newest link first. A linked
card that the person cannot read must not show.
The section must have the actions `Verknüpfen` (`Link`) and `To-Do anlegen` (`Add to-do`) for a
person who may change the element.

Reason: One list for all links keeps the detail short. The kind on each row tells the reader
what opens.

Test: A frontend unit test of the list sorts an Event, a card and an invoice and checks the
order.
