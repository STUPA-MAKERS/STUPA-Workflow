---
id: "000924"
title: A final protocol can be marked as approved
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
---

# A final protocol can be marked as approved

A person with `protocol.finalize` in the Gremium must be able to mark a final protocol as
approved. The mark must name the meeting that approved the protocol. The protocol list must
show the mark.

Reason: The Gremium approves each protocol in its next Sitzung.

Test: An integration test that marks a draft protocol and gets 409.
