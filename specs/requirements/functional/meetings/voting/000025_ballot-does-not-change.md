---
id: F/meetings/voting/000025
title: A cast ballot does not change
kind: functional
status: draft
scope:
  - backend/app/modules/voting
  - frontend/src/app/features/voting
owner: frederikbeimgraben
updated: 2026-11-05
---

# A cast ballot does not change

A voter must not change or withdraw a ballot after the cast. The UI must not offer
"Stimme nach Abgabe änderbar".

Reason: A changed ballot rewrites a decision after the fact.
