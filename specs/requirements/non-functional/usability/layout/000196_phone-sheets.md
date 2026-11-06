---
id: "000196"
title: The phone opens pickers as bottom sheets
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

# The phone opens pickers as bottom sheets

On the phone, a picker, a filter and a secondary pane open as the shared bottom sheet. Every
desktop view must be reachable without a picker. Search bars stay at the top.
