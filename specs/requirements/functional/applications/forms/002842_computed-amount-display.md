---
id: "002842"
title: A computed amount shows as money
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/shared/formly/types/formly-display.type.ts
  - frontend/src/app/shared/forms/answer-view/answer-view.component.ts
scope:
  - frontend/src/app/shared/forms
  - frontend/src/app/shared/formly
---

# A computed amount shows as money

The form and the answer view must show the value of a computed amount field as an amount in EUR
in the language of the interface, for example `29,40 €` in German and `€29.40` in English.

Reason: A raw value such as `29.4` does not look like money, and it is not the amount that the
server stores.

Test: The unit tests of the display type and of the answer view show `29,40 €` for the value
`29.4`.
