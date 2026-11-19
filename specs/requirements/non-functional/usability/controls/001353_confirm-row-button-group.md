---
id: "001353"
title: The buttons of a dialog footer form a button group with a filled main action
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/vendor/ui-kit/src/lib/button-group/button-group.component.spec.ts:ButtonGroupComponent"
implementation:
  - frontend/vendor/ui-kit/src/styles/button-group.scss
  - frontend/vendor/ui-kit/src/lib/dialog/dialog.component.html
  - frontend/src/app/features/todos/move-sheet
  - frontend/src/app/shared/ui/chat/chat.component.html
  - frontend/src/app/features/meetings/calendar-subscribe
  - frontend/src/app/features/meetings/public-join
  - frontend/src/app/features/public-meeting
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The buttons of a dialog footer form a button group with a filled main action

The buttons of a dialog footer and of a confirm row (Abbrechen and the main action, such as
"Verschieben" of a to-do card or "Speichern" of an edited chat message) must form a button
group in the look of 001350. The main action must keep the accent fill, and the other buttons
must be tonal.

Reason: In a dialog a person must tell the confirm from the cancel at a glance. A head has no
such pair, so its buttons are all tonal.

Test: The spec of `ButtonGroupComponent` in the ui-kit expects the accent fill for the main
button of a group with `main`.
