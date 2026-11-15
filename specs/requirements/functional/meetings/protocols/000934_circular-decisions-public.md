---
id: "000934"
title: A circular decision is public where the protocol is public
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/protocol/test_public_decisions_unit.py:test_list_holds_the_circular_votes_of_a_public_protocol"
  - "backend/tests/unit/modules/protocol/test_circular_protocol.py:test_public_form_of_a_circular_vote_has_no_name"
implementation:
  - backend/app/modules/protocol/circular.py
  - backend/app/modules/protocol/public_decisions.py
  - backend/app/modules/protocol/public.py
  - frontend/src/app/features/public-protocols/public-protocol-detail.component.ts
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/public-protocols
---

# A circular decision is public where the protocol is public

The circular votes that a protocol lists (000916) must show in each public form of this
protocol: the public PDF, the public protocol page and the list of public decisions (000926).
A circular decision must be public only when this protocol is public. A public circular
decision must show its question, its date, its result and the sums of the votes. It must never
show the name of a person.

Reason: A decision of the Gremium is the same decision in a Sitzung and in an
Umlaufverfahren. The public PDF, the public page and the list must not disagree.

Test: A backend unit test reads the public protocol and the public decisions of a public
protocol with a closed circular vote and finds the vote in both.
