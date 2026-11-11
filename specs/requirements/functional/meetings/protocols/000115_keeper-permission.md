---
id: "000115"
title: The keeper holds protocol.write
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/meetings/keepers.py
  - backend/app/modules/livevote/service/handover.py
  - frontend/src/app/features/meetings/handover-dialog/handover-dialog.component.ts
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
---

# The keeper holds protocol.write

The protocol keeper must hold `protocol.write`. The server checks it at the assignment and at
each handover. A handover takes effect "ab jetzt" or "ab nächstem TOP".
