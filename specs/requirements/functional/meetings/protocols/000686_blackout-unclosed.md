---
id: "000686"
title: An open blackout marker stops the finalize
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/protocol/test_protocol_blackout.py:test_start_finalize_refuses_an_open_marker"
implementation:
  - backend/app/modules/protocol/service/finalize.py
  - frontend/src/app/shared/markdown/markdown.util.ts
  - frontend/src/app/features/meetings/top-sheet
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
---

# An open blackout marker stops the finalize

If a protocol text has a blackout marker without its closing `%%`, or a blackout block (000965)
without its closing line, the finalize must refuse with
problem+json code `blackout_unclosed` and must name the TOP. The editor must show the open
marker as an error.

Reason: An open marker blacks out nothing, so the name goes to the public variant.

Test: A backend test finalizes a protocol with an open marker and gets the error.
