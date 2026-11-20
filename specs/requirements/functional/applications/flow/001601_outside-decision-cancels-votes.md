---
id: "001601"
title: A decision made outside the platform cancels the open votes
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/flow/outside_decision.py
scope:
  - backend/app/modules/flow
  - frontend/src/app/pages/applications
---

# A decision made outside the platform cancels the open votes

When a person records a decision made outside the platform (001600), every open vote of the
Antrag must be cancelled in the same way as when the Antrag leaves the vote state (000235). The
voters must get the mail `vote_cancelled`.

Reason: An open vote on the platform must not decide the Antrag a second time after the Gremium decided in its meeting.

Test: A backend integration test opens a vote, records an outside decision and checks that the vote is cancelled.
