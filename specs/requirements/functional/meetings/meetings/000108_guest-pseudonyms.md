---
id: "000108"
title: Guest names become pseudonyms
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - backend/app/modules/protocol
---

# Guest names become pseudonyms

A guest who leaves or withdraws must become "Gast n" at once. All guest names must become "Gast
1 … n" when the meeting closes and again when the protocol becomes final. Open and rejected
requests must be deleted at the close. The audit log must keep only the guest id.
