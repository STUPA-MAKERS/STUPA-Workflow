---
id: "001481"
title: A row of the Verwaltung list is an ordinary list row
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/pages/admin/admin-list/admin-list.component.html
scope:
  - frontend/src/app/pages/admin
  - frontend/src/app/pages/account
---

# A row of the Verwaltung list is an ordinary list row

Each page in the list of Verwaltung and Konto must be an `app-list-item`: the icon as the lead,
the title, and the description of the page as the second line. The row of the open page is
selected. The row has the same look in both layouts.

Reason: An ordinary list/detail page has one kind of row everywhere.

Test: A unit test expects one `app-list-item` per visible page, with the description as its
subtitle and the open page selected.
