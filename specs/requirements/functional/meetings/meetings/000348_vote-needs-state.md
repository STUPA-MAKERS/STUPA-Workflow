---
id: "000348"
title: A vote on an Antrag needs the matching vote state
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/livevote
  - backend/app/modules/voting
---

# A vote on an Antrag needs the matching vote state

A vote on an Antrag TOP opens only when the Antrag is in a vote state of the Gremium of the
vote.

Reason: Else the members cast ballots on a vote that cannot close.
