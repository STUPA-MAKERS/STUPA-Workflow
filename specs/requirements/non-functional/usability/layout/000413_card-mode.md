---
id: "000413"
title: A table in card mode keeps its controls in the card head
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/vendor/ui-kit/src/lib/data-table/data-table.component.html
  - frontend/vendor/ui-kit/src/lib/data-table/data-table.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A table in card mode keeps its controls in the card head

In card mode, the checkbox and the ⋮ menu must be in the card head. A selection must highlight
the whole card.
