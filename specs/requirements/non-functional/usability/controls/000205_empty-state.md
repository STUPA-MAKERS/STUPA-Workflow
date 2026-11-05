---
id: "000205"
title: Empty states use one component
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - frontend/src/app/
  - ui-kit
---

# Empty states use one component

An empty list, pane or dialog uses `app-empty-state` with ghost rows, a message and at most one
tonal action. Ghost rows that fill a pane are aligned at the top. Only a plain empty state is
centred.
