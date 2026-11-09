---
id: "000562"
title: A phone toast shows at the top
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.scss
  - frontend/vendor/ui-kit/shell/src/shell/shell.component.scss
scope:
  - frontend/vendor/ui-kit
---

# A phone toast shows at the top

On a phone, a toast must show at the top of the window, below the top safe area. It must
span the width of the window less a gutter of 12px on each side.

Reason: At the bottom, the toast covered the FAB and the end of the list.
