---
id: "000106"
title: Guests vote or only watch
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# Guests vote or only watch

A meeting with guests is in the mode "Gäste dürfen abstimmen" or "nur zuschauen". A vote with
guests has no quorum and needs a majority of the cast ballots. A non-public TOP has no guest
vote. The mode cannot change from vote to watch while a vote with guests is open.
