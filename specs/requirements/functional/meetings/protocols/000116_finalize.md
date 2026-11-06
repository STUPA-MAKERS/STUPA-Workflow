---
id: "000116"
title: Finalize needs a closed meeting and protocol.finalize
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/protocol/service.py
  - frontend/src/app/features/meetings/finalize-protocol-dialog
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
  - backend/app/modules/gremien
---

# Finalize needs a closed meeting and protocol.finalize

A protocol must be finalizable only when the meeting is closed. The person must have write
access to the protocol and the Gremium permission `protocol.finalize`. The header of the
protocol must list all keepers.
