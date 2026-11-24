---
id: "002861"
title: The form fills the planned price from the preferred offers
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages/applications
---

# The form fills the planned price from the preferred offers

When a person picks positions in the form of a Bestellung, the form must set the planned price
to the sum of the preferred offers of these positions. The form must not change a planned price
that the person typed.

Reason: The preferred offer is the price that the Gremium approved. The prefill saves the copy
by hand and makes a later deviation visible.

Test: A frontend unit test picks two positions and reads the sum, then types a price, picks a
third position and reads the typed price.
