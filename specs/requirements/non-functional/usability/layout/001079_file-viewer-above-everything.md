---
id: "001079"
title: The file viewer lies above everything
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/vendor/ui-kit/src/lib/file-viewer/file-viewer.component.spec.ts:FileViewerComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/file-viewer
scope:
  - frontend/vendor/ui-kit/src/lib/file-viewer
  - frontend/src/app
---

# The file viewer lies above everything

The file viewer must cover the whole viewport on every screen width. It must lie above the
rail, the heads, the side sheets, the bottom sheets and the dialogs. This applies also when the
viewer opens from a side sheet, a dialog or a card. Only the toasts may lie above the viewer.

Reason: The glass (`backdrop-filter`) and the fade (`mask-image`) of a sheet make the sheet the
box of a fixed child. A viewer that opens in a card then covers only the card, and the rail and
the board stay visible beside it.

Test: Component test of the kit: the open viewer is in the top layer (`:popover-open`). A
screenshot of a PDF opened from a to-do card on desktop and on a phone shows the viewer over
the full viewport.
