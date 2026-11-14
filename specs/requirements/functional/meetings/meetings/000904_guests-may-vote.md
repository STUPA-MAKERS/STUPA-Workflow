---
id: "000904"
title: Guest ballots are a Gremium setting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/gremien
  - backend/app/modules/admin
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - frontend/src/app/pages/admin
---

# Guest ballots are a Gremium setting

A Gremium must have the switch `guestsMayVote`, and a new Gremium must start with the value
off. While the switch is off, the server must refuse the guest mode "Gäste dürfen abstimmen"
with 422 `guests_vote_off`. A new meeting must then start in the mode "nur zuschauen".

Reason: The Geschäftsordnung gives guests no vote. Only a Gremium that decides it differently
lets guests vote.

Test: An integration test that sets the guest mode of a meeting.
