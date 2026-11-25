---
id: "003096"
title: The detail of an Event shows the Mollie money
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# The detail of an Event shows the Mollie money

The section `Verkauf` (003084) of an Event with assigned payments must also show the sum of the
paid payments, the refunds, the chargebacks, the Mollie fees and the sum that Mollie paid out
to the bank, with the date of each settlement. Each person who reads the Event must see these
sums.

Reason: The sales in pretix say what the guests bought. The sums of Mollie say what money
arrived at the bank and what the fees took.

Test: A frontend unit test opens an Event with assigned payments and reads the fees and the
paid-out sum.
