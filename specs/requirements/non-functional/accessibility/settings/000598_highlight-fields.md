---
id: "000598"
title: Highlighted fields have black text on yellow
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:highlightedFields"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
  - frontend/vendor/ui-kit/src/styles/_field.scss
  - frontend/vendor/ui-kit/src/styles/_check.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Highlighted fields have black text on yellow

With the switch "Eingabefelder hervorheben" on (000593), every input field (text, text area,
select, date, time, amount and search field) must have a yellow background, black text, a black
label, a black placeholder, black icons and a 2 px black edge. Every checkbox, radio button and
switch must have a yellow box with a 2 px black edge, and its mark must be black. The error
edge and the focus ring must stay visible on the yellow. This applies in both themes. The
switch is off by default, because no system setting asks for it.

Reason: A person with low vision or with a cognitive impairment must find the fields of a
form at a glance.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts`.
