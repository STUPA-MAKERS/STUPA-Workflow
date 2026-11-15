---
id: "000092"
title: A meeting opens in a configured window
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/livevote/test_open_window.py:test_check_open"
  - "backend/tests/unit/modules/livevote/test_meeting_status_machine.py:test_start_in_the_open_window_needs_no_confirmation"
implementation:
  - backend/app/modules/livevote/open_window.py
  - frontend/src/app/features/meetings/open-window.util.ts
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - backend/app/modules/admin
---

# A meeting opens in a configured window

A meeting must open at the earliest `open_lead_minutes` before its planned start. The value must
be an admin setting with the start value 60. From this point on, the open must need no extra
confirmation. Before this point, the server must refuse the open with 409 `meeting_too_early`.

Reason: One value is sufficient. A second point with an extra confirmation dialog gave a second
setting and a second step, but the lead already makes the decision when the lead selects "Sitzung
eröffnen".

Test: A unit test of the window and of the open in the window.
