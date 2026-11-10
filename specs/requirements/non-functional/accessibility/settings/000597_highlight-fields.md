---
id: "000597"
title: Highlighted fields have black text on yellow
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Highlighted fields have black text on yellow

With the switch "Eingabefelder hervorheben" on (000593), every input field (text, text area,
select, date, time, amount and search field) must have a yellow background, black text, a
black label, a black placeholder, black icons and a 2 px black edge. The error edge and the
focus ring must stay visible on the yellow. This applies in both themes. The switch is off
by default, because no system setting asks for it.

Reason: A person with low vision or with a cognitive impairment must find the fields of a
form at a glance.

Test: `frontend/src/app/shared/ui/surface-contrast.spec.ts` with the field tokens.
