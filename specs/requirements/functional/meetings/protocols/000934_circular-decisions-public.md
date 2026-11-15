---
id: "000934"
title: A circular decision is public where the protocol is public
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/protocol/circular.py
  - backend/app/modules/protocol/public_decisions.py
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
