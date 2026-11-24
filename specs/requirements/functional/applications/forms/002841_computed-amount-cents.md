---
id: "002841"
title: A computed amount is a whole number of cents
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/forms/validation.py
scope:
  - backend/app/modules/forms
---

# A computed amount is a whole number of cents

The server must round a computed amount to two decimal places, half up (29.405 becomes 29.41).
When the expression cannot be evaluated, or its result is no number, not finite or below 0,
the server must answer 422 with an error at the amount field. The Antrag must then not get an
amount from an older value.

Reason: The amount is money, and a booking holds whole cents. A broken expression must not give
a stored amount that nobody can see is wrong.

Test: `backend/tests/unit/modules/forms/test_computed_amount.py` rounds 29.405 to 29.41 and refuses a negative
result and a missing input with 422.
