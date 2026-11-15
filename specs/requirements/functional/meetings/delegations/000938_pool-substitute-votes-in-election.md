---
id: "000938"
title: A pool substitute votes in an election
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/delegations/test_delegate_limit_live.py:test_a_pool_substitute_of_the_lead_votes_in_an_election"
implementation:
  - backend/app/modules/delegations/service.py
scope:
  - backend/app/modules/voting
  - backend/app/modules/delegations
---

# A pool substitute votes in an election

A pool substitute that the lead entered for a member (000420) must be able to cast the ballot
of this member in an election. The refusal of a delegation ballot (000910) must apply only to
a delegation that is no pool substitution.

Reason: A substitute from the pool holds the seat of the member. A pool substitute that takes
a free seat (000113) votes in an election, and the entry by the lead must not differ.

Test: An integration test that casts the ballot of a lead-entered pool substitute in an
election.
