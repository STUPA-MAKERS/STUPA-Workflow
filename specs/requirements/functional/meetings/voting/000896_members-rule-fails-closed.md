---
id: "000896"
title: A members rule without an eligible count rejects
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/voting
---

# A members rule without an eligible count rejects

A vote with the rule `members_majority` or `members_two_thirds` must use the eligible count of
the vote (000381). A missing eligible count or a count of 0 must give the result `rejected`.

Reason: A missing count must not let a small number of ballots pass a motion.

Test: A unit test of `tally.result` without an eligible count.
