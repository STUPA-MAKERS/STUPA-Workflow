---
id: "000951"
title: The lead corrects the attendance until the protocol is final
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/livevote/test_attendance_rules.py:test_closed_meeting_freezes_the_own_report_and_the_lead_corrects"
  - "backend/tests/integration/modules/livevote/test_attendance_rules.py:test_final_protocol_freezes_the_attendance"
  - "backend/tests/unit/modules/livevote/test_livevote_cov.py:test_set_for_corrects_a_former_member_of_a_closed_meeting"
  - "frontend/src/app/features/meetings/attendance-sheet/attendance-sheet.component.spec.ts:protocolLocked"
implementation:
  - backend/app/modules/meetings/attendance_service.py
  - frontend/src/app/features/meetings/attendance-sheet/attendance-sheet.component.ts
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# The lead corrects the attendance until the protocol is final

A person with write access to a meeting must be able to set and to reset the attendance of a
member after the close of the meeting, until the protocol of the meeting is final. A protocol
in its render counts as final. After such a change the meeting must count its present members
again (000946). The result of a closed vote must not change. The own report of a member must
stay closed with the close of the meeting, except the late excuse (000922).

After the close, the change must also be possible for a person who is no longer a member of
the Gremium but has an attendance record in the meeting. A change after the close must not
change a substitution: it must free no seat of a substitute, and a delegation of the member
must not refuse it.

Reason: The keeper finds a wrong attendance when the keeper writes the protocol. The final
protocol carries the attendance list, so a change after the finalization makes the PDF and
the platform disagree. A person who left the Gremium after the meeting is still in its
list. The votes of a closed meeting are over, so a substitution has no effect any more and
stays as the record of the meeting.

Test: An integration test in which the lead sets the attendance of a closed meeting with a
draft protocol and the present count follows, and one in which a final protocol answers 409.
A frontend unit test that finds the choices of the lead in a closed meeting with a draft.
