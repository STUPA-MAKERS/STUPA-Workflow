---
id: "000115"
title: The keeper holds protocol.write
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/protocol
---

# The keeper holds protocol.write

The protocol keeper must hold `protocol.write`. The server checks it at the assignment and at
each handover. A handover takes effect "ab jetzt" or "ab nächstem TOP".
