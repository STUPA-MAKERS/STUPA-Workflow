---
id: "000353"
title: A vote with guests has no quorum
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote
  - backend/app/modules/voting
scope:
  - backend/app/modules/livevote
  - backend/app/modules/voting
---

# A vote with guests has no quorum

A vote with guests must be possible only on a public TOP. It must have no quorum and must need
a majority of the cast ballots. The eligible count must be the present members plus the
admitted guests.
