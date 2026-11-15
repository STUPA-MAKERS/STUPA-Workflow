---
id: "000910"
title: An election takes no delegation ballot
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/delegations/test_delegate_limit_live.py:test_an_election_takes_no_delegation_ballot"
  - "backend/tests/unit/modules/voting/test_voting_service_unit.py:test_cast_election_refuses_the_delegation_ballot_403"
implementation:
  - backend/app/modules/voting/service
  - backend/app/modules/delegations/service.py
  - backend/app/modules/livevote/service/votes.py
  - backend/app/modules/gremien/models.py
scope:
  - backend/app/modules/voting
  - backend/app/modules/delegations
  - backend/app/modules/gremien
  - backend/app/modules/admin
---

# An election takes no delegation ballot

An election must refuse a ballot of a delegation with 403 `delegation_not_in_election`. A
Gremium must have the switch `delegationInElections`, off at the start, that allows such a
ballot.

Reason: The Organisationssatzung excludes the Stimmrechtsübertragung for Wahlen.

Test: An integration test that casts a delegation ballot in an election.
