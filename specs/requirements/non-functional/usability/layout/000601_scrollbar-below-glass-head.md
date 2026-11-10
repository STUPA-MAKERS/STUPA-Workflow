---
id: "000601"
title: The scroll bar of a list column starts below its glass head
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - frontend/vendor/ui-kit/src/styles/list-detail.scss
scope:
  - frontend/vendor/ui-kit
---

# The scroll bar of a list column starts below its glass head

On a wide screen, the scroll bar of the rows of a list column with a glass head (000527) must
start at the lower edge of the head, not at the top edge of the screen. The thumb must not go
under the glass of the head. The scroll bar keeps the thin grey look of every other scroll bar,
and it runs down to the bottom edge of the screen as the rows do.

Reason: The rows reach up under the head, so their scroll bar started at the top edge of the
screen too. Its track ran through the head beside the filter chips, and at the top of the list
the thumb sat under the glass, blurred and cut.

Test: Screenshots of a list column on a desktop width (Buchungen, Rechnungen, Verwaltung) with
the rows at the top and scrolled, in the light and the dark theme: the thumb begins below the
head. A browser without a track margin for scroll bars (Firefox) keeps the thin bar over the
full height.
