---
id: "002990"
title: The funding hint is the help of the field
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "frontend/src/app/shared/forms/formly-mapper.spec.ts:toFormlyFields"
implementation:
  - frontend/src/app/shared/forms/formly-mapper.ts
scope:
  - frontend/src/app/shared/forms
---

# The funding hint is the help of the field

The form must show the help of a `funding` field (000135) as its hint and must not add a text
with the cost total. A required `funding` field without help must show no hint. An optional
`funding` field without help must show "Leer lassen, um die volle Summe zu beantragen." without
an amount. The error text of a value above the cost total must name the cost total.

Reason: The finance officer writes the hint in the form editor. A text that the form adds is out
of the officer's control, and the cost line (001630) already shows the total.

Test: The unit tests of the formly mapper show exactly the help "X" at a required field, no hint
at a required field without help, the text without an amount at an optional field without help,
and the cost total in the error text.
