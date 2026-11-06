---
id: "000095"
title: The protocol and votes can be prepared before the open
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/protocol/service.py
  - backend/app/modules/livevote/vote_build.py
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - backend/app/modules/protocol
---

# The protocol and votes can be prepared before the open

The protokollant must be able to write the protocol text before the meeting opens. A vote
question must be preparable without the open of the vote.
