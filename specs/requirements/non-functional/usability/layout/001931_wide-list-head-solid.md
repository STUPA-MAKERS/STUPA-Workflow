---
id: "001931"
title: The head of a wide list column stays solid, also on a fast scroll
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/src/styles/styles.spec.ts:SolidWideHead"
implementation:
  - frontend/vendor/ui-kit/src/styles/list-detail.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The head of a wide list column stays solid, also on a fast scroll

On a wide screen, the head of a list column (title, search field, filters and the buttons
beside them) must be solid in the page colour in every state, also while a group head (a
month or a day) sticks right under it. No row and no group head may show between or behind
the parts of the head, also when the list scrolls fast.

Reason: The head lost its colour while a group head was right under it, because the group
head was to carry the colour of the whole head. The page notes that state one frame or more
late. On a fast scroll, rows and a group head that the next one pushed up then showed behind
the search field and between the filters (Anträge, Aktivität).

Test: A unit test of the kit styles expects the solid colour of the head for that state on a
wide screen, after the rule that clears the glass.
