---
id: "000619"
title: In very high contrast, a row that opens something has a yellow title
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:rowTitleYellow"
implementation:
  - frontend/vendor/ui-kit/src/lib/list-item/list-item.component.scss
  - frontend/vendor/ui-kit/src/lib/data-table/data-table.component.scss
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# In very high contrast, a row that opens something has a yellow title

While "Sehr hoher Kontrast" is on, the title of each row that a person can press must be yellow.
The other texts of the row stay white, and the row has no edge. This applies to a list row, a
table row, a row that folds open, a row of the budget tree, a tile and a day of a calendar. The
open row must have a yellow fill and black text.

Reason: A row that opens something is a control (000614). A yellow title marks it like a link, and
the status and the amount stay easy to read in white.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts` expects the yellow title in a
list row, a table row and a tile, and the yellow fill of the open row.
