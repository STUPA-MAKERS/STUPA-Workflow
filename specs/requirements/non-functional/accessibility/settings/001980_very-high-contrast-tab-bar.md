---
id: "001980"
title: In very high contrast, a tab bar is one group with a yellow bar under the open tab
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:veryHighTabBar"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
scope:
  - frontend/vendor/ui-kit
---

# In very high contrast, a tab bar is one group with a yellow bar under the open tab

While "Hoher Kontrast" is on, a tab bar (`app-tabs`, also inside `app-tab-pager`) must show as
one group, as in the normal look:

- Each tab has yellow text on black. A tab has no edge and no fill of its own.
- The distance between the texts of the tabs stays as in the normal look.
- The white line under the tabs runs through under all tabs.
- The open tab has bold text and a yellow bar of 4 px under its text, over the white line. In a
  paged tab bar the bar moves with the swipe.
- A focused tab has a yellow ring of 3 px around its text. The ring ends above the yellow bar,
  so the ring and the bar of the open tab both show.

The light and the dark look do not change.

This is an exception to 000615 for the tab bar: there the chosen control of a choice is the
yellow fill and the other controls have the yellow edge. A group of chips with the role of a tab
bar stays a group of chips under 000615.

Reason: A row of yellow boxes reads as a row of buttons, not as tabs. The bar under the open tab
and the bold text show the open tab by shape, not by colour only. Yellow on black has a contrast
of more than 7:1.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts` (`veryHighTabBar`) expects
the yellow text without an edge for each tab, the 4 px bar and the bold text for the open tab,
and the ring of a focused tab.
