---
id: "000562"
title: A toast shows at the top of a phone and at the bottom end of a wide screen
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.scss
  - frontend/vendor/ui-kit/shell/src/shell/shell.component.scss
  - frontend/vendor/ui-kit/src/lib/toast/toast.service.ts
scope:
  - frontend/vendor/ui-kit
---

# A toast shows at the top of a phone and at the bottom end of a wide screen

On a phone, a toast must show at the top of the window, below the top safe area. It must
span the width of the window less a gutter of 12px on each side. Only the newest toast must
be visible there: a new toast must replace the visible toast. The live region must still
announce every toast.

On a screen wider than a phone, the toasts must stay at the bottom end of the window, one
above the other, each 24rem wide at most.

Reason: At the bottom of a phone, the toast covered the FAB and the end of the list, and a
stack of toasts covers too much of a small screen.
