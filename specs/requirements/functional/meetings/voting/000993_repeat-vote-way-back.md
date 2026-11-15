---
id: "000993"
title: A repeated application vote moves the application in one step and has a way back
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/livevote/test_meeting_vote_edit_repeat.py:test_cancelled_repeat_gives_the_application_its_first_decision_back"
  - "backend/tests/unit/modules/voting/test_repeat_restore.py:test_the_restore_moves_back_and_swaps_the_decisions"
  - "backend/tests/unit/modules/flow/test_flow_service.py:test_revert_status_leaves_the_commit_to_the_caller"
  - "frontend/src/app/features/apply/status-timeline.component.spec.ts:StatusTimelineComponent"
implementation:
  - backend/app/modules/voting/repeat.py
  - backend/app/modules/voting/router.py
  - backend/app/modules/livevote/vote_repeat.py
  - backend/app/modules/flow/service.py
  - frontend/src/app/features/apply/status-timeline.component.ts
scope:
  - backend/app/modules/voting
  - backend/app/modules/livevote
  - backend/app/modules/flow
  - frontend/src/app/features/apply
---

# A repeated application vote moves the application in one step and has a way back

The open of a repeat of a closed application vote moves the application back into its vote
state. The move back and the open of the repeat must commit together. A refused open must
leave the application in the state that the first vote decided.

The cancel of an open repeat must bring the application back to the state that the first
vote decided, and the decision of the first vote must be valid again. The timeline of the
application must show this step with the note `vote:repeat-cancelled`. The cancel must not
move an application that left the vote state by another way.

Reason: An application in a vote state without a vote has no way out except a manual status
change. After a cancelled repeat, the first vote is the only decision of the Gremium, so the
application and the protocol must say the same.
