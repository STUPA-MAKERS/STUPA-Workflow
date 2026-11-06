---
id: "000348"
title: A vote on an Antrag needs the matching vote state
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote
  - backend/app/modules/voting
scope:
  - backend/app/modules/livevote
  - backend/app/modules/voting
---

# A vote on an Antrag needs the matching vote state

A vote on an Antrag TOP must open only when the Antrag is in a vote state of the Gremium of the
vote.

Reason: Else the members cast ballots on a vote that cannot close.
