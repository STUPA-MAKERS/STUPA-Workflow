---
id: "003010"
title: Every hint of a form comes from the form config
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "frontend/src/app/shared/formly/types/formly-positions.type.spec.ts:hints"
  - "backend/tests/unit/modules/forms/test_forms_validation.py:test_field_hints"
implementation:
  - backend/app/shared/config_schemas.py
  - frontend/src/app/shared/forms/form-hints.ts
  - frontend/vendor/ui-kit/views/form-editor/src/form-editor-view.component.html
scope:
  - backend/app/modules/forms
  - frontend/src/app/shared/forms
  - frontend/src/app/shared/formly
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# Every hint of a form comes from the form config

The code must not hold the text of a hint in a form. A hint shows only when the form config holds
its text, in the languages of the form. Without a text the form shows nothing at that place and
asks nothing. A hint has no switch: an empty text is off.

A `positions` field has these hint texts (`validation.hints`):

| Key | Where the form shows it | Today in the code |
|---|---|---|
| `below` | below the sum row of 003008 | "Gesamtkosten …, davon beantragt …, … pro Person" (001630, 001631) |
| `placeholderValue` | at an offer whose amount looks like a placeholder (001640) | "Wie ein Platzhalter." |
| `placeholderLabel` | at an offer whose name has fewer than 3 characters | "Weniger als 3 Zeichen." |
| `placeholderDuplicate` | at an offer whose name another offer has | "Steht schon bei einem anderen Angebot." |
| `useNoOffers` | below the offers of a position with a placeholder offer | "Gibt es keine Vergleichsangebote, schalte … ein." |
| `noOffers` | at a position without comparison offers | "Bitte begründe, warum …" |
| `noFileTitle`, `noFileBody` | the question before a submit without a file (001731) | "Ohne Anhang einreichen?" and its text |

A hint text may hold placeholders in braces. `{key}` inserts the answer of the field `key` of the
form, and `{costTotal}` and `{amount}` insert the values of 001670. A money value shows as money
(`1.200,00 €`), a number as a number. An unknown key or an empty value inserts nothing.
`{noOffersSwitch}` inserts the label of the switch "Keine Vergleichsangebote".

The form editor must show the hint texts at the field, as a text per language, with the list of the
placeholders. A placeholder check of 001640 without its text shows neither the ring nor a line.
The existing forms get no text: after the update they show no hint until a person enters one.

This spec replaces the switches of 003000, 003001 and 003003 and the texts of 001630, 001631,
001632, 001640 and 001731. The checks behind a hint, the computation of the values and the
switches of 003002 and 003004 stay.

Reason: The texts depend on the rules and the language of one student body. A hint that the code
writes is a rule of one student body in the code of all.

Test: A frontend unit test renders a `positions` field without hint texts and finds no hint, then
with the text "Summe {costTotal}" and finds "Summe 1.200,00 €". A backend unit test saves the hint
texts of a field and reads them back.
