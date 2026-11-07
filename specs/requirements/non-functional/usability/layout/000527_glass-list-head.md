---
id: "000527"
title: A list head is one glass surface over its rows
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-07
implementation:
  - frontend/src/app/pages/todos
  - frontend/vendor/ui-kit
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A list head is one glass surface over its rows

Where the rows of a list scroll under the head of the list, the head must be one frosted glass
surface over the rows. The head holds the title, the search bar, the filter chips and a pinned
group head. The rows must run to the bottom edge of the screen without a fade. No state of the
scroll, a fast scroll too, must show a row sharp through the head. The page "To-Dos" follows
this rule in "Alle", in "Liste" and below a board with rows. On a phone a board shows one
page per column under a tab line. Each page scrolls by itself, and the head with the tab line
is one frosted glass surface over the page, the same as the head of "Meine To-Dos".

Reason: The rows stay in view as a blur behind the head, so the user sees that the list
continues. A fade under a glass head hides rows for no gain. The classes of the head follow
the scroll one frame or more late, so the glass of the head must not depend on them.

Test: `frontend/vendor/ui-kit/src/lib/sticky-bar/sticky-bar.component.spec.ts` (the bar finds
rows that a page turns into a scroll container) and a check of the screenshots.
