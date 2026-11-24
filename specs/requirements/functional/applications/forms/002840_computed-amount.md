---
id: "002840"
title: The server computes a computed amount
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/forms/validation.py
  - backend/app/modules/applications/service/create.py
  - backend/app/modules/applications/service/edits.py
  - backend/app/modules/applications/service/type_change.py
scope:
  - backend/app/modules/forms
  - backend/app/modules/applications
---

# The server computes a computed amount

A `computed` field with `isPromoted: true` and `promoteTarget: "amount"` is the amount field of
the form. At the create, at each edit and at a change of the Antragsart, the server must compute
every `computed` field from the answers again. The server must not use a value that the client
sends for a `computed` field.

The server must store each computed value in `data` under the key of its field. The value of the
amount field must be the `amount` of the Antrag in EUR. A form rule must read this value as
`amount` and under the key of the field.

Reason: A fixed rate (for example 0.35 € per km) gives an amount that nobody types in and nobody
can change. Without the computed amount, `amount` is `null` and every flow guard that compares
`amount` is false.

Test: `backend/tests/unit/modules/forms/test_computed_amount.py`: `km = 84` gives `amount = 29.40` also when the
client sends `summe = 999`, and an edit to `km = 100` gives `amount = 35.00`.
