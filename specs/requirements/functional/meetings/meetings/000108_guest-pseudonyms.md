---
id: "000108"
title: Guest names become pseudonyms
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - backend/app/modules/protocol
---

# Guest names become pseudonyms

A guest who leaves or withdraws becomes "Gast n" at once. All guest names become "Gast 1 … n"
when the meeting closes. Open and rejected requests are deleted at the close. The audit log
keeps only the guest id.
