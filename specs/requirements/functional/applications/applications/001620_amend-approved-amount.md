---
id: "001620"
title: An approved Antrag takes a new approved amount
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# An approved Antrag takes a new approved amount

A person with the permission `application.amend_decision` must be able to change the approved
amount of an Antrag in a state with the flag `Bewilligt`. The dialog
`Genehmigten Betrag ändern` (`Change approved amount`) must ask for the new amount, a reason of
at least 10 characters, and the decision that allows the change: the date and the Gremium. The
change must write a new decision that replaces the old one (000132) and keeps its conditions.
The state of the Antrag must not change. A migration must give the permission to the roles
`finanzreferent` and `haushaltsbeauftragte` when these roles exist.

Reason: Prod data holds 5 Folgeanträge only for small extra costs, one of them for 22 €, and one detour through the draft state.

Test: A backend integration test changes the amount and checks the new decision, the old decision and the unchanged state.
