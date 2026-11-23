---
id: "001483"
title: The round frame of an admin page cuts nothing at rest
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation:
  - frontend/src/app/pages/admin/admin-list/admin-list.component.ts
  - frontend/src/app/pages/admin/admin-list/admin-list.component.html
  - frontend/src/app/pages/admin/admin-list/admin-list.component.scss
scope:
  - frontend/src/app/pages/admin
  - frontend/src/app/pages/account
---

# The round frame of an admin page cuts nothing at rest

On a wide screen, the page body of Verwaltung and Konto scrolls inside a round frame (001480,
ui-kit:000193). The top corners of that frame must be round only while the page is scrolled
down. At the top of the page, the top corners are square, so a control at the top right of the
page head, for example the language dropdown of "Rollen & Rechte", shows with all its corners.
The other edges of the frame stay as they are.

Reason: The page head starts at the top edge of the frame, and a control at the right end of
the head sits in the round corner. The corner cut off the top right corner of the control. The
round corner is only needed while content scrolls past the top edge, and at the top of the page
no content is above that edge.

Test: A unit test of the list page expects the scrolled class on the page body after a scroll
and no scrolled class at the top. Screenshots of "Rollen & Rechte" at the top and scrolled, in
the light and the dark theme and in the high and the very high contrast mode.
