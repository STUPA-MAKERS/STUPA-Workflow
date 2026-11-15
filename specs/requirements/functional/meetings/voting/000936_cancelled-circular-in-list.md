---
id: "000936"
title: The vote list shows a circular vote that an objection ended
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/voting/circular.py
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

Test: A frontend unit test loads the list with a cancelled circular vote and a cancelled
motion and finds only the circular vote.
