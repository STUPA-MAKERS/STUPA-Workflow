---
id: "000530"
title: The search bar of the start page stays at the top on the phone
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-07
implementation:
  - frontend/src/app/pages/dashboard
scope:
  - frontend/src/app/pages/dashboard
---

# The search bar of the start page stays at the top on the phone

On the phone, the search bar of the start page with the avatar button must stay pinned at the
top of the screen while the page scrolls. The bar must be the frosted glass of the sticky bar of
the list pages. The gap between the search field and the edge of the glass must be the same on
all four sides. On the desktop, the search bar must scroll with the page.

Reason: The search and the account menu are the first controls of the start page. A bar that
scrolls away makes the user scroll back up to reach them. The list pages already pin their
search bar, so the start page behaves the same.

Test: `frontend/src/app/pages/dashboard/dashboard.component.spec.ts` (the search bar is in a
sticky bar on the phone and not on the desktop) and a check of the screenshots.
