---
id: "002001"
title: The marks of the navigation come in one read, not on every page change
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "backend/tests/integration/modules/activity/test_activity.py:test_the_navigation_marks_come_in_one_read"
  - "frontend/src/app/layout/rail-status.service.spec.ts:RailStatusService"
implementation:
  - backend/app/modules/activity/navigation.py
  - backend/app/modules/activity/router.py
  - backend/app/modules/livevote/service/listing.py
  - frontend/src/app/layout/rail-status.service.ts
  - mcp/antragsplattform_mcp/tools/session.py
scope:
  - backend/app/modules/activity
  - frontend/src/app/layout
---

# The marks of the navigation come in one read, not on every page change

The app must read the marks of the navigation (open tasks, new tickets, a live meeting, a
waiting event) with one request, `GET /api/navigation/status`. Each mark must apply the read
rule of its own module, and a mark of a feature that is off must be empty. The app must read
the marks at sign-in, after a write that the server answered, after a meeting changes its
status, when the app becomes visible again and every 60 seconds while it is visible. A page
change alone must not read the marks.

Reason: The marks took 5 to 8 requests after each page change, among them the whole task list
and up to 4 pages of meetings. They ran at the same time as the reads of the new page and
slowed it down.

Test: The integration test reads the marks of a person with an open to-do and a live meeting
of their Gremium, and of a live meeting of another Gremium. The test of the rail service reads
that a navigation sends no request and that a write, a status change and the return to the app
each send one.
