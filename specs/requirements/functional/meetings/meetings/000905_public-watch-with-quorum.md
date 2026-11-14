---
id: "000905"
title: A Gremium with a quorum lets guests only watch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# A Gremium with a quorum lets guests only watch

A meeting of a Gremium with a quorum must allow public participation by QR code only in the
mode "nur zuschauen". The server must refuse the mode "Gäste dürfen abstimmen" for such a
meeting. A meeting of a Gremium without a quorum must follow `guestsMayVote` (000904).

Reason: The Sitzungen of STUPA and AStA are hochschulöffentlich, and a guest ballot cannot
count for a quorum.

Test: An integration test that switches public participation on for a Gremium with a quorum.
