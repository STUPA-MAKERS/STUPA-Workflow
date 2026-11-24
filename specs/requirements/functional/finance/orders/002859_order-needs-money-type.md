---
id: "002859"
title: A Bestellung needs an Antrag of a type with money
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/budget
  - backend/app/modules/applications
---

# A Bestellung needs an Antrag of a type with money

The server must create a Bestellung only for an Antrag of a type with money (`hasBudget`). It
must answer 422 `application_type_without_budget` for a different type.

Reason: An Antrag of a type without money has no amount and no Kostenstelle
(F/finance/budget/001033), so a purchase has nothing to stand against.

Test: A backend integration test refuses a Bestellung for an Antrag of a type without money.
