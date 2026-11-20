---
id: "001930"
title: A pane page scrolls inside itself, so the rail stays in place
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/pane-page.styles.spec.ts:panePages"
implementation:
  - frontend/src/app/pages/activity/activity.component.scss
scope:
  - frontend/src/app/
---

# A pane page scrolls inside itself, so the rail stays in place

A page that fills the window beside the rail (a pane page, `pane-page`) must have a scroll
container of its own: its list, its columns or a kit layout that scrolls. The window must not
scroll on a pane page. The navigation rail must keep its place and show all its entries, from
the top edge on, while the content of the page scrolls.

Reason: A pane page and the frame of the shell are one window high, and the rail sticks only
inside that frame. When the list of a pane page grows past the window, the window scrolls, and
the rail scrolls away with the page: its top entries are cut off. Aktivität did this after it
became a pane page.

Test: A unit test reads every pane page and expects a scroll container in its template or
styles, and expects the list of Aktivität to scroll inside the page.
