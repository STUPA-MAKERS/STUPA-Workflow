---
id: "000353"
title: A vote with guests has no quorum
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/livevote
  - backend/app/modules/voting
---

# A vote with guests has no quorum

A vote with guests is possible only on a public TOP. It has no quorum. The eligible count is
the present members plus the admitted guests.
