---
id: "000916"
title: The next protocol lists the Umlaufverfahren
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/protocol
  - backend/app/modules/voting
---

# The next protocol lists the Umlaufverfahren

The protocol of a meeting must list each circular vote (000914) of the Gremium that closed
after the meeting before. Each entry must show the question, the result and the counts.

Reason: The Geschäftsordnung asks the protocol of the next Sitzung to hold the Beschluss and
its result.

Test: An integration test of the protocol assembly with a closed circular vote.
