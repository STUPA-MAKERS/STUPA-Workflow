---
id: "000939"
title: A vote without a meeting counts the members at its open
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/voting/test_circular_vote.py:test_a_draft_counts_the_members_at_its_open"
implementation:
  - backend/app/modules/voting/service
  - backend/app/modules/voting/circular.py
scope:
  - backend/app/modules/voting
---

# A vote without a meeting counts the members at its open

A vote without a meeting must read the number of the eligible members of its Gremium when it
opens. This number must apply until the vote closes. A draft must not keep the number of the
time it was made.

Reason: The members that are eligible at the open get a ballot. The majority of the members
(000894) must count the same persons.

Test: An integration test that makes a circular draft, adds a member, opens the vote and reads
the number of eligible members.
