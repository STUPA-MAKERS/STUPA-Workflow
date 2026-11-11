---
id: "000675"
title: A phone list row ends with a menu or with nothing
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - frontend/src/app/pages/tickets
  - frontend/src/app/features/meetings
  - frontend/src/app/features/gremien
  - frontend/src/app/shared/ui/row-chevron
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A phone list row ends with a menu or with nothing

On the phone a row of a list page must end with the ⋮ menu when the row has actions. A row
without actions must end with its last text. A row of a list page must not end with an
arrow. This applies to Tickets, Sitzungen and Gremien, which lose the arrow.

A row inside a detail view or a table keeps its arrow, because there not every row opens a
page.

Reason: On the phone every row of a list page opens a page, so the arrow says nothing of its
own. The lists end their rows in three ways.

Test: A unit test of the three pages at phone width expects no chevron in a list row.
