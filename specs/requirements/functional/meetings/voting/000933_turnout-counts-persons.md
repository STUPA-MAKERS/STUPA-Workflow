---
id: "000933"
title: The turnout of a running vote counts persons
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/delegations/test_delegate_limit_live.py:test_one_cast_writes_the_own_and_each_represented_ballot"
  - "backend/tests/integration/modules/delegations/test_delegate_limit_live.py:test_an_external_delegate_casts_for_every_represented_member"
implementation:
  - backend/app/modules/voting/service.py
  - backend/app/modules/voting/models.py
  - backend/app/modules/livevote/service/votes.py
scope:
  - backend/app/modules/voting
  - backend/app/modules/livevote
---

# The turnout of a running vote counts persons

The turnout line of a running vote ("1 von 1 Anwesenden haben abgestimmt") must count the
persons who cast. One cast must count once, for however many voting rights it exercises. The
result of a closed vote must count the ballots.

Reason: The line compares with the present persons. A member who transferred the vote is not
present, so a count of ballots can be larger than the number of present persons.

Test: An integration test that casts once with two delegations and reads a turnout of 1.
