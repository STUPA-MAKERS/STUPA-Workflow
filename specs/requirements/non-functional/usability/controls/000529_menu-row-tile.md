---
id: "000529"
title: A menu row is an inset rounded tile
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/vendor/ui-kit/src/styles/_option-menu.scss
  - frontend/vendor/ui-kit/src/lib/row-menu/row-menu.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A menu row is an inset rounded tile

The rows of a popover menu (a dropdown, a filter chip, the ⋮ menu) must sit 6px inside the
edge of the menu. The hover, the focus and the press of a row must show as a tile with a corner
radius of 8px. In the phone sheet, the rows stay the tiles of a row group.

Reason: A full-width row that shrinks on press leaves a gap on both sides and looks like a loose
grey block. An inset tile shrinks inside the menu and follows its curve.

Test: `touch.spec.ts` of the ui-kit reads the padding of the menu and the corners of a row.
