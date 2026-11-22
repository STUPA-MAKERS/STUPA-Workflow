---
id: "000940"
title: A repeat meeting names its first meeting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/livevote/test_repeat_first_meeting.py:test_a_repeat_meeting_without_a_first_meeting_is_refused"
  - "backend/tests/integration/modules/livevote/test_public_meeting.py:test_meeting_kind_place_and_form"
  - "frontend/src/app/features/meetings/create-meeting-dialog/create-meeting-dialog.component.spec.ts:repeatOfId"
  - "frontend/src/app/features/meetings/meeting-head/meeting-head.component.spec.ts:link"
implementation:
  - backend/app/modules/livevote/repeat.py
  - backend/app/modules/livevote/service/lifecycle.py
  - frontend/src/app/features/meetings/meeting-kind.util.ts
  - frontend/vendor/ui-kit/views/meeting/src/meeting-head-view.component.ts
scope:
  - backend/app/modules/livevote
  - backend/app/modules/meetings
  - frontend/src/app/features/meetings
---

# A repeat meeting names its first meeting

A meeting of the kind `repeat` (000903) must name an earlier meeting of the same Gremium as
its first meeting. A request that makes a repeat meeting without this meeting must be refused.
The page of the repeat meeting must link the first meeting.

Reason: The repeat quorum (000902) applies only to the Wiederholungssitzung of a Sitzung that
had no quorum. Without the first meeting, each meeting can take the lower quorum.

Test: A backend unit test makes a repeat meeting without a first meeting and gets a 422.
