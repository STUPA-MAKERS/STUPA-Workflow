---
id: "002782"
title: The format bar shows below the selection
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation:
  - frontend/vendor/ui-kit/markdown-editor/src/markdown-editor.component.ts
scope:
  - frontend/vendor/ui-kit/markdown-editor
---

# The format bar shows below the selection

The format bar (002780) must show below the last line of the selection, with its start at the
start of the selection. When the space below the selection in the visible area is too small for
the bar, the bar must show above the first line of the selection. The bar must stay in the
width of the editor. While a pointer drags a selection, the bar must not show. The bar must
show when the pointer is released. This rule applies on every screen width.

Reason: Below the selection, the bar does not cover the menu of the system (copy, paste) that a
phone shows above a selection.

Test: A unit test of the editor measures the place of the bar for a selection at the top and at
the bottom of the visible area.
