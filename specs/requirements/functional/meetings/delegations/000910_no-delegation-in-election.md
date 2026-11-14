---
id: "000910"
title: An election takes no delegation ballot
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
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
