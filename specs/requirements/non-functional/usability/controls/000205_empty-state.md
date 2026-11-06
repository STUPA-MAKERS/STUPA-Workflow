---
id: "000205"
title: Empty states use one component
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/
  - frontend/vendor/ui-kit
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Empty states use one component

An empty state must use `app-empty-state` with a message and at most one tonal action. Ghost
rows must align at the top of their pane. Only a plain empty state must be centred. 000412 says
where ghost rows show.
