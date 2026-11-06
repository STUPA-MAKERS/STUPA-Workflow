---
id: "000029"
title: A vote can be deleted only as draft or cancelled
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# A vote can be deleted only as draft or cancelled

A vote in the state `draft` or `cancelled` must be deletable, in a meeting and without a
meeting. An open or closed vote must answer 409 `vote_not_deletable`. The UI must show
"Beschlussfrage löschen" only for a draft or cancelled vote.

Reason: An open or closed vote is part of the meeting record.
