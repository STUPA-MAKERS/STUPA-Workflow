---
id: "000116"
title: Finalize needs a closed meeting and protocol.finalize
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/protocol
  - backend/app/modules/gremien
---

# Finalize needs a closed meeting and protocol.finalize

A protocol can be finalized only when the meeting is closed. The person needs write access to
the protocol and the Gremium permission `protocol.finalize`. Every Gremium role with
`session.manage` also has `protocol.finalize`. The header of the protocol lists all keepers.
