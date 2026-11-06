---
id: "000519"
title: A form error is a text next to the field
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A form error is a text next to the field

A field error must be a text that is linked to the field with `aria-describedby`. On a
failed submit, the focus must go to the first field with an error. A required field must show
this in its label.

Reason: WCAG 3.3.1, 3.3.2 and 3.3.3.
