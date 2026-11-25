---
id: "003006"
title: A funding field without help shows no hint
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "frontend/src/app/shared/forms/formly-mapper.spec.ts:toFormlyFields"
implementation:
  - frontend/src/app/shared/forms/formly-mapper.ts
scope:
  - frontend/src/app/shared/forms
---

# A funding field without help shows no hint

A `funding` field (000135) without help must show no hint, also when it is optional. The form
must not add the text "Leer lassen, um die volle Summe zu beantragen.". This replaces the last
part of 002990.

Reason: The finance officer writes the hint in the form editor. A text that the form adds is out
of the officer's control.

Test: The unit tests of the formly mapper show no hint at an optional `funding` field without
help.
