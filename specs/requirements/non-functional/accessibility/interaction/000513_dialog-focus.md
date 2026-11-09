---
id: "000513"
title: A dialog keeps the focus inside
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/vendor/ui-kit/src/lib/focus/focus-dialog.directive.spec.ts:FocusDialogDirective"
  - "frontend/vendor/ui-kit/src/lib/focus/focus-trap.spec.ts:trapTab"
  - "frontend/vendor/ui-kit/src/lib/dialog/dialog.component.spec.ts:DialogComponent"
  - "frontend/vendor/ui-kit/src/lib/side-sheet/side-sheet.component.spec.ts:SideSheetComponent"
  - "frontend/vendor/ui-kit/src/lib/fab/fab.component.spec.ts:FabComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/focus/focus-dialog.directive.ts
  - frontend/vendor/ui-kit/src/lib/focus/focus-trap.ts
  - frontend/vendor/ui-kit/src/lib/dialog/dialog.component.ts
  - frontend/vendor/ui-kit/src/lib/side-sheet/side-sheet.component.ts
  - frontend/vendor/ui-kit/src/lib/fab/fab.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A dialog keeps the focus inside

A dialog and a sheet must move the focus into themselves when they open. The focus must not
leave them while they are open. Escape must close them, and the focus must go back to the
control that opened them.

Reason: WCAG 2.1.2 and 2.4.3.
