---
id: "000949"
title: A circular decision shows in the list of decisions and in no protocol
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/protocol/public_decisions.py
  - backend/app/modules/protocol/service.py
scope:
  - backend/app/modules/protocol
  - backend/app/modules/voting
  - frontend/src/app/features/public-protocols
---

# A circular decision shows in the list of decisions and in no protocol

A protocol must not list a circular vote (000914): not in its text, not in its PDF and not on
its public page. The list of public decisions (000926) must show each closed circular vote of
a Gremium whose protocols are public. The entry must show from the close of the vote. It must
show the question, the date of the end, the result and the sums of the votes. It must never
show the name of a person. A circular vote that an objection cancelled (000915) must not show
in this list.

Reason: A block that the platform writes into a protocol by itself is not a part of the
Sitzung that the protocol records. The list of decisions is the one place for a decision
outside a Sitzung.

Test: A backend unit test reads the public decisions of a public Gremium with a closed
circular vote and finds the vote, and a test of the protocol assembly finds no circular block.
