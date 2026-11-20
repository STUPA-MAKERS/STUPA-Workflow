---
id: "001651"
title: An admin page lists the forced status changes
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

# An admin page lists the forced status changes

The admin page `Erzwungene Status` (`Forced status changes`) must show one list of the forced
status changes, the newest first. Each row names the Antrag, the time, the path (from state, to
state), the reason and the note, and opens the Antrag. Filters narrow the list by reason, by
path and by period. The default period is the last 90 days. The page shows no counts and no
dialog. The page needs the permission `audit.read`.

Reason: A path that admins force often is a way that the flow does not have. The filter by path shows which transition to add.

Test: A backend unit test filters the forced changes by reason and by path in a period; a frontend unit test shows one list with its filters.
