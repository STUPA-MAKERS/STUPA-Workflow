---
id: "000686"
title: An open blackout marker stops the finalize
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
---

# An open blackout marker stops the finalize

If a protocol text has a blackout marker without its end `}}`, the finalize must refuse with
problem+json code `blackout_unclosed` and must name the TOP. The editor must show the open
marker as an error.

Reason: An open marker blacks out nothing, so the name goes to the public variant.

Test: A backend test finalizes a protocol with an open marker and gets the error.
