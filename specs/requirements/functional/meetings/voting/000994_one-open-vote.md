---
id: "000994"
title: A meeting has one open vote at a time
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/livevote/test_meeting_vote_edit_repeat.py:test_a_vote_does_not_open_beside_an_open_vote"
  - "backend/tests/unit/modules/livevote/test_livevote_cov.py:test_open_prepared_vote_waits_for_the_open_vote"
implementation:
  - backend/app/modules/livevote/vote_open.py
  - backend/app/modules/livevote/router.py
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# A meeting has one open vote at a time

The server must refuse the open of a meeting vote while another vote of the same meeting is
open. This applies to a vote that opens at its create and to the open of a prepared vote. The
answer must be 409 `vote_open_exists`. A prepared vote must still be possible beside an open
vote.

Reason: The room and the beamer show one vote. The page already offers no second open, but a
second tab, the MCP server or a slow connection can send it. Two open votes hide one of them
from the voters.
