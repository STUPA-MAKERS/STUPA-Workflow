---
id: "001016"
title: A search bar in a paged tab does not stick
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - frontend/src/app/features/gremien/gremium-members/gremium-members.component.html
  - frontend/src/app/features/gremien/gremium-decisions/gremium-decisions.component.html
scope:
  - frontend/src/app
---

# A search bar in a paged tab does not stick

The search field and the filter chips of a tab inside a tab pager (`app-tab-pager`) must stay in
the flow of the page and must not use `app-sticky-bar`. They must sit right below the tab line.

Reason: The pager scrolls sideways, so it is the scroll container of every sticky element in it.
It never scrolls down, so a sticky bar moves down by the height of the shell header and covers
the first group heading and the first rows.

Test: A screenshot check of the tabs Mitglieder and Beschlüsse of a Gremium on a phone.
