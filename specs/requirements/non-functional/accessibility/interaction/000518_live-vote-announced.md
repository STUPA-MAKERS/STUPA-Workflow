---
id: "000518"
title: The live vote announces its changes
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/src/app/features/voting/vote-cast.component.spec.ts:VoteCastComponent"
  - "frontend/src/app/features/voting/voting-page/voting.component.spec.ts:VotingComponent"
  - "frontend/src/app/features/voting/vote-announce.util.spec.ts:VoteAnnounce"
implementation:
  - frontend/src/app/features/voting/vote-announce.util.ts
  - frontend/src/app/features/voting/vote-cast.component.ts
  - frontend/src/app/features/voting/voting-page/voting.component.ts
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
