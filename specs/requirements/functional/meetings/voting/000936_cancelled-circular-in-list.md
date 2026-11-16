---
id: "000936"
title: The vote list shows a circular vote that an objection ended
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/voting/test_vote_list.py:test_list_keeps_only_the_cancelled_votes_of_an_objection"
implementation:
  - backend/app/modules/voting/listing.py
  - frontend/src/app/features/voting/voting-page/voting.component.ts
scope:
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# The vote list shows a circular vote that an objection ended

The list of votes must show a circular vote (000914) that an objection cancelled (000915).
The row must show the state "Abgebrochen". The status chip "Beendet" must include it. A
cancelled vote of each other kind must not show in the list.

Reason: A circular vote has no Antrag and no Sitzung. Without the row in the list, no page
leads to a cancelled circular vote.

Test: A backend unit test reads the list with the reason `objection` and finds the filter for
the cancelled votes in the query.
