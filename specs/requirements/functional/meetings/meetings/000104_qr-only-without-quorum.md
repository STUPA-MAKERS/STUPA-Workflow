---
id: "000104"
title: Public participation only without quorum
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# Public participation only without quorum

A meeting can allow public participation by QR code only if its Gremium has no quorum. The
server refuses the switch for a Gremium with a quorum.

Reason: Only Fachschaften without a quorum use guests. STUPA and AStA never do.
