---
id: "000193"
title: A scroll area cuts at the edge of a surface
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/pages/admin/admin-frame/admin-frame.component.scss
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.scss
  - frontend/vendor/ui-kit/src/styles/_frosted.scss
  - frontend/vendor/ui-kit/src/styles/list-detail.scss
  - frontend/vendor/ui-kit/src/lib/sticky-bar/sticky-bar.component.scss
  - frontend/vendor/ui-kit/src/lib/list-group/list-group.component.scss
  - frontend/vendor/ui-kit/src/lib/scroll-fade
  - frontend/vendor/ui-kit/src/styles/_scroll-fade.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - frontend/src/app/features/todos/card-detail
---

# A scroll area cuts at the edge of a surface

A scroll area must not fade at its ends. Its content must cut hard at an edge that the user can
see. At each kind of place, the content must cut as this table says:

| Place | Where the content cuts |
| --- | --- |
| A scroll area that fills a surface, for example a detail sheet, a dialog, a side sheet, a bottom sheet or a form | At the rounded edge of that surface, as the detail of a list does. |
| A column on the page background that ends above the bottom edge of the screen, for example the agenda of a Sitzung | The column lies on a surface of its own with rounded corners, and the content cuts at its edge. |
| A column that reaches the bottom edge of the screen, for example the cost-centre tree of the Haushalt | At the edge of the screen. The column has no surface of its own. |
| A list inside a dialog or a sheet, for example the bookings of a cost centre or the attendance | At the rounded frame of the list itself. The rows run to the sides of the frame, without side padding. |
| The page body of the administration sheet on a wide screen | At a rounded frame that is exactly as wide as the fields, 24 px inside the sheet, so that a field that scrolls past an end keeps its rounded corners. |
| The scroll part of the navigation rail | The scroll part lies on a surface of its own with rounded corners (001331). |
| A row of chips that scrolls sideways on a phone | At the edge of the screen. The row runs from screen edge to screen edge. |
| The message log of a chat | At its rounded frame. |
| The rows of a list column on a wide screen | At the lower edge of the list head (000527). |
| A real line, for example a tab line on the phone | At that line. |

In the very high contrast mode (000605), a scroll area draws no extra line at an end where its
content cuts at the edge of a surface, because that edge is already drawn.

Reason: A fade at one place and a hard cut at another made the app look inconsistent. A cut at
an edge that the user sees looks intended, and the user still sees that the content goes on,
because the cut runs through a row.

Test: Screenshots of each kind of place in the table, in the light and the dark theme and in the
very high contrast mode, and a check that no `fade-y` or `fade-x` mixin and no scroll-fade mask
is left in `frontend/src` and in the ui-kit.
