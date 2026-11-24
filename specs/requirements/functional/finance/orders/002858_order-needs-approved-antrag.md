---
id: "002858"
title: A Bestellung needs an approved Antrag of a type with money
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/orders/service.py
scope:
  - backend/app/modules/orders
  - backend/app/modules/applications
---

# A Bestellung needs an approved Antrag of a type with money

The server must create a Bestellung only for an Antrag of a type with money (`hasBudget`) that
is in a state with the flag approved (F/applications/flow/000571). It must answer 422
`application_type_without_budget` for a different type and 409 `application_not_approved` for a
different state. It must read only the flag and must not compare the key of a state. A
Bestellung that exists must stay editable when the Antrag leaves the approved state.

Reason: Before the approval there is no money to spend, and an Antrag of a type without money
has no amount and no Kostenstelle (F/finance/budget/001033).

Test: A backend integration test refuses a Bestellung for a submitted Antrag and for an Antrag
of a type without money, creates one for an approved Antrag and edits it after the Antrag left
the state.
