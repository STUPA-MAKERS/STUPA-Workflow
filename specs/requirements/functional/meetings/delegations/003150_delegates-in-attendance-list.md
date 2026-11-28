---
id: "003150"
title: The attendance list of a meeting shows the delegates
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "backend/tests/integration/modules/delegations/test_delegates_attendance.py:test_the_roster_lists_a_delegate_who_is_no_member"
  - "backend/tests/integration/modules/delegations/test_delegates_attendance.py:test_the_lead_and_the_delegate_set_the_attendance"
  - "frontend/src/app/features/meetings/attendance-sheet/attendance-sheet.component.spec.ts:AttendanceSheetComponent"
implementation:
  - backend/app/modules/meetings/roster.py
  - backend/app/modules/meetings/attendance_service.py
  - backend/app/modules/meetings/schemas.py
  - frontend/vendor/ui-kit/views/meeting/src/attendance-sheet-view.component.ts
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - mcp/antragsplattform_mcp
---

# The attendance list of a meeting shows the delegates

The attendance list of a meeting must have a row for each delegate who holds a delegation
with the voting right in the meeting (002900), also for a delegate who is no member of the
Gremium. The row must name the members that the delegate represents ("vertritt Max Muster").
The rows of the delegates who are no members must be a section "Vertretungen" below the
members. A delegate who is a member must stay in the member rows, with the same line. The
meeting lead must be able to set the attendance of a delegate like that of a member. The
delegate must be able to report the own attendance like a member.

Reason: A Vertretung sits in the Sitzung in place of a member. The list must show who is in
the room, and the lead must be able to record it.

Test: An integration test reads the roster of a meeting with a delegate who is no member,
sets the delegate present as the lead and reports the own attendance as the delegate.
