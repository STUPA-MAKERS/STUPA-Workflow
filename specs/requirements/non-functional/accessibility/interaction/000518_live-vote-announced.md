---
id: "000518"
title: The live vote announces its changes
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - frontend/src/app/features/voting
---

# The live vote announces its changes

When a vote opens, closes or shows its result, the voting page must announce it in a live
region. The announcement must name the TOP and the vote.

Reason: The vote comes over the WebSocket without a user action, so a screen reader user does
not know that the page changed.
