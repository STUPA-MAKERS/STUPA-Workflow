---
id: "000935"
title: A vote takes its quorum from the Gremium
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/livevote/vote_build.py
  - backend/app/modules/livevote/schemas.py
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - mcp
---

# A vote takes its quorum from the Gremium

A vote in a meeting must take its quorum in percent from the settings of the Gremium
(000900, 000902). The request that makes or changes a vote must not accept a quorum in
percent. The dialog of a vote must not offer one.

Reason: The Satzung sets the Beschlussfähigkeit of a Gremium. A value on one vote can set it
to 0.

Test: A backend unit test sends `quorumPercent` with a new vote and gets a 422.
