---
id: "000925"
title: The keeper sends the protocol draft to the members
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/protocol
  - backend/app/modules/notifications
  - frontend/src/app/features/meetings
---

# The keeper sends the protocol draft to the members

A person with write access to a draft protocol must be able to send its PDF to the members of
the Gremium. Each page of this PDF must have the watermark "Entwurf". The send must not change
the state of the protocol.

Reason: The Geschäftsordnung asks for the draft of the protocol two weeks after the Sitzung.

Test: An integration test that sends the draft and reads the state.
