---
id: "003008"
title: The sum of the positions is a row below the positions
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "frontend/src/app/shared/formly/types/formly-positions.type.spec.ts:sumRow"
implementation:
  - frontend/src/app/shared/formly/types/formly-positions.type.html
  - frontend/src/app/shared/formly/types/formly-positions.type.scss
scope:
  - frontend/src/app/shared/formly
---

# The sum of the positions is a row below the positions

A `positions` field must show the sum of its positions as a row below the last position and
above the line of 001630 and the add button. The row must have its own surface in the style of a
collapsed position: the same background, corner radius, padding and height. The row must show
the text `Gesamt` (`Total`) at the start and the sum at the end, in the column of the value of a
position. The head of the field must not show a sum. The row must show also when the field has
no position, with the sum 0,00 €.

Reason: The sum to the right of the legend is small and far from the values that it adds up. A
row in the style of the positions puts the sum below the values of the positions.

Test: A frontend unit test renders a `positions` field with one position of 1.200 € and finds
the row with `Gesamt` and `1.200,00 €`, and no sum in the head.
