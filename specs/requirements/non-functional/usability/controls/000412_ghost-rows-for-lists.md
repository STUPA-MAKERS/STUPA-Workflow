---
id: "000412"
title: Ghost rows are only for lists
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - frontend/src/app/
  - ui-kit
---

# Ghost rows are only for lists

Ghost rows show only for an empty list or a search without a hit. They mirror the shape of the
real rows and take the full width. A pane, a 404 page, the admin start and a forbidden pane
use the `plain` look with an icon. Dropdown no-hit lines, inline values, errors and the
desktop Kanban columns have no empty state.
