---
id: "000379"
title: The close and its branch commit together
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/voting
  - backend/app/modules/flow
---

# The close and its branch commit together

The close of a vote and its flow branch commit in one transaction. If the branch fails, the
vote stays closed with its result, and `vote_branch_blocked` is audited.
