---
id: "000027"
title: A tie in an election is decided by lot
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/livevote/test_livevote_cov.py:test_patch_close_waits_for_a_pending_lot"
  - "frontend/src/app/features/meetings/close-meeting-dialog/close-meeting-dialog.component.spec.ts:CloseMeetingDialogComponent"
implementation:
  - backend/app/modules/voting/election.py
  - backend/app/modules/livevote/service/lifecycle.py
  - backend/app/modules/livevote/service/votes.py
  - frontend/src/app/features/meetings/close-meeting-dialog/close-meeting-dialog.component.ts
scope:
  - backend/app/modules/voting
  - backend/app/modules/livevote
  - frontend/src/app/features/voting
  - frontend/src/app/features/meetings
---

# A tie in an election is decided by lot

A tie at the seat limit of a personnel election must be decided by lot. The platform must draw
the lot. There must be no runoff route. A stored result with `runoff` must still show. The further
Wahlgänge of an election by the majority of the members follow 000971.

A meeting must not close while an election of the meeting waits for the lot: the close must
answer 409 `lot_pending`, and the dialog of the close must name the reason. An election that
was voted on again does not count.

Reason: The lead draws the lot in the room. A lot that is drawn after the close, or after the
protocol is final, gives a result that the protocol does not hold.
