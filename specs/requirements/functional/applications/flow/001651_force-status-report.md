---
id: "001651"
title: An admin page counts the forced status changes
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/flow/forced_report.py
  - backend/app/modules/flow/forced_router.py
  - frontend/src/app/pages/admin/forced-status/forced-status.component.ts
scope:
  - backend/app/modules/flow
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# An admin page counts the forced status changes

The admin page `Erzwungene Status` (`Forced status changes`) must show the forced status
changes in a period. The default period is the last 90 days. The page must show the count per
reason and the count per path (from state, to state), the largest count first. A click on a
count must list the Anträge of that count on the page, below the tables, without a dialog. A
second click on the same count must hide the list. The page needs the permission `audit.read`.

Reason: A path that admins force often is a way that the flow does not have. The count shows which transition to add.

Test: A backend unit test counts forced changes per reason and per path in a period.
