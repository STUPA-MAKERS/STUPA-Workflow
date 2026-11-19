---
id: "001341"
title: A dialog or sheet head is as far from the top as from the side
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/vendor/ui-kit/src/lib/dialog/dialog.component.spec.ts:DialogComponent"
  - "frontend/vendor/ui-kit/src/lib/side-sheet/side-sheet.component.spec.ts:SideSheetComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/dialog
  - frontend/vendor/ui-kit/src/lib/side-sheet
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A dialog or sheet head is as far from the top as from the side

In the head of a dialog or a side sheet, the top of the capital letters of the title must be
as far from the top edge as the title is from the side edge. On a phone sheet with a handle,
the distance is measured from the lower edge of the handle. The close button stays centred
on the title line.

This is the rule of 001340 for dialogs and sheets: a dialog and a side sheet use 24px, a
dialog on a phone uses 16px below the handle, and a bottom sheet uses 24px below the handle.

Reason: The capitals of a dialog title, for example "Sitzung anlegen", sat 36px below the top
edge, and the title sat 24px from the side. The head looked as if it had more room above
than at the side.

Test: Unit tests of the dialog and the side sheet read their styles and expect the top padding
of the head to be the side distance less the 12px of the head above the capitals.
