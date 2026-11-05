---
id: F/meetings/voting/000029
title: A vote can be deleted only as draft or cancelled
kind: functional
status: draft
scope:
  - backend/app/modules/voting
  - frontend/src/app/features/voting
owner: frederikbeimgraben
updated: 2026-11-05
---

# A vote can be deleted only as draft or cancelled

A vote in the state `draft` or `cancelled` can be deleted. An open or closed vote must answer
409 `vote_not_deletable`. The UI shows "Beschlussfrage löschen" only for a draft or cancelled
vote.

Reason: An open or closed vote is part of the meeting record.
