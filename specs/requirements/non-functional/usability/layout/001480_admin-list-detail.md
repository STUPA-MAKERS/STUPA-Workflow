---
id: "001480"
title: Verwaltung and Konto are ordinary list/detail pages
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/pages/admin/admin-list/admin-list.component.ts
  - frontend/src/app/pages/admin/admin-list/admin-list.component.html
  - frontend/src/app/pages/admin/admin-list/admin-list.component.scss
  - frontend/src/app/pages/admin/admin-list/frame-modes.ts
  - frontend/vendor/ui-kit/src/lib/list-detail/list-detail-layout.component.ts
scope:
  - frontend/src/app/pages/admin
  - frontend/src/app/pages/account
---

# Verwaltung and Konto are ordinary list/detail pages

`/admin` and `/account` must be list/detail pages built on `app-list-detail`, the same as the
Gremien and the Tickets. The list is the navigation of the area: the title, the search
"Einstellungen durchsuchen" (Verwaltung only) and the groups of pages. The list has no
"Zustand" tiles. The detail is the open page. The app must have no frame component of its own
for these areas: no own split, no own sheet, no own bar, no own swipe back and no own scroll
memory of the sheet.

On a wide screen, the list and the open page sit side by side. The open page scrolls inside a
round frame 24px inside the sheet (000193), and a sticky bar of the page has the colour of the
sheet. Without an open page, the detail
shows the empty pane (000665). One pane at a time, `/admin` and `/account` show the list, and a
page shows with the bar of `app-list-detail`, which names the page (`barTitle`) and leads back
to the list.

Reason: The admin frame differed from a list/detail page only in details, and it repeated
about 400 lines of layout that `app-list-detail` already has.

Test: A unit test of the list page expects `app-list-detail`, the groups filtered by permission,
feature and search, and the detail open on every page below `/admin` and `/account`.
