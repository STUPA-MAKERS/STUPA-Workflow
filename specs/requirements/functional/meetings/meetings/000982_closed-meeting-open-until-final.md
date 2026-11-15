---
id: "000982"
title: A closed meeting stays open for corrections until its protocol is final
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/livevote/test_meeting_title.py:test_closed_meeting_takes_corrections_until_the_protocol_is_final"
  - "backend/tests/integration/modules/livevote/test_meeting_title.py:test_final_protocol_closes_the_corrections"
  - "backend/tests/unit/modules/livevote/test_livevote_cov.py:test_rename_after_close_follows_the_protocol"
  - "backend/tests/unit/modules/livevote/test_livevote_cov.py:test_patch_closed_keeps_its_kind"
  - "frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.spec.ts:canEditTop"
  - "frontend/src/app/features/meetings/meeting-settings-dialog/meeting-settings-dialog.component.spec.ts:closedMeeting"
implementation:
  - backend/app/modules/livevote/service/lifecycle.py
  - backend/app/modules/meetings/agenda_service.py
  - frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.ts
  - frontend/src/app/features/meetings/meeting-settings-dialog/meeting-settings-dialog.component.ts
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# A closed meeting stays open for corrections until its protocol is final

A person with the right for the change must be able to change the data of a closed meeting
until the protocol of the meeting is final. A protocol in its render counts as final. This
holds for:

- the title, the text and the mark "nicht öffentlich" of an agenda item,
- the title, the date, the times, the place and the form of the meeting,
- the attendance (000951).

The list of the agenda items must stay closed with the close of the meeting: a person must
not add, remove or move an agenda item of a closed meeting. The kind of the meeting, its first
meeting (for a repeat), its keeper and its guest settings must stay closed too: a change of
one of them must answer 409 `meeting_closed`. A person must not open a vote in a closed
meeting, and the result of a closed vote must not change. After the protocol is final, each
change of the list above must answer 409 `protocol_final`.

Reason: The keeper finds a wrong title, a wrong time or a missing mark "nicht öffentlich"
when the keeper writes the protocol. One rule for all data is simpler than a lock per field.
The final protocol carries the data, so a change after the finalization makes the PDF and the
platform disagree. The list and the order of the agenda items are what the room saw, and the
votes hang on them. The kind sets the quorum of the votes and the count of the absences, so a
change after the close changes what the closed votes and the absence list mean.

Test: An integration test in which the lead renames an agenda item, marks it "nicht
öffentlich" and changes the place of a closed meeting with a draft protocol, in which the add,
the remove and the move of an agenda item answer 409 `meeting_closed`, and in which each change
answers 409 `protocol_final` after the finalization. A unit test in which a new kind of a
closed meeting answers 409 `meeting_closed`. A frontend unit test that finds the
rename and the settings of a closed meeting with a draft protocol, and none of them with a
final protocol.
