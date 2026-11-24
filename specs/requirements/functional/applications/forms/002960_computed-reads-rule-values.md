---
id: "002960"
title: A computed field reads the values of a form rule
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/forms/validation.py
  - frontend/src/app/shared/forms/form-rules.ts
  - frontend/src/app/shared/forms/formly-mapper.ts
scope:
  - backend/app/modules/forms
  - frontend/src/app/shared/forms
---

# A computed field reads the values of a form rule

A `compute` expression must read the same values as a form rule (001670): the answers by field
key, `amount` and `costTotal`, as `rule_context` makes them. The server and the form must
compute the `computed` fields in field order, and an expression must read the values of the
`computed` fields before it. `amount` must be the computed amount only after its field.

Reason: A rate of funding or an own share is a value of the cost total, and the applicant and
the Gremium must see it while they fill in the form. The server and the form must give the
same value, or the form shows a value that the Antrag does not store.

Test: The shared fixture `frontend/src/app/shared/forms/form-rules.fixture.json` runs in the
backend and the frontend unit tests: costs of 1,200 € and a funding of 1,000 € give
`foerderquote = 0.8333` and `eigenanteil = 200.00` on both sides.
