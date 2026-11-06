---
id: "000104"
title: Public participation only without quorum
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# Public participation only without quorum

A meeting must allow public participation by QR code only if its Gremium has no quorum. The
server must refuse the switch for a Gremium with a quorum.

Reason: Only Fachschaften without a quorum use guests. STUPA and AStA never do.
