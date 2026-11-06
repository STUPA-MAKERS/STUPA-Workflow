---
id: "000378"
title: The database serializes ballots
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/voting
---

# The database serializes ballots

A unique constraint per vote and voter, or the secret marker, must make a second ballot answer
409 `already_voted`. Cast, close and cancel must lock the vote row.

Reason: A last ballot must not land after the tally.
