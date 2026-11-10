---
id: "000614"
title: In very high contrast, yellow shows what a person can press
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/e2e/06-axe.spec.ts:everyControlShowsYellow"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# In very high contrast, yellow shows what a person can press

While "Sehr hoher Kontrast" is on (000605), every element that a person can press must show
yellow. It shows yellow as a fill, as an edge or as its text. A text that a person cannot press
must not be yellow. White text must not be a control.

The rules 000598 and 000615 to 000620 say which of the three forms a control has.

Reason: A person with very low vision must see at a glance what reacts to a press. A list of
single controls leaves out each new control.

Test: `frontend/e2e/06-axe.spec.ts` opens each page of its route list and measures
every element that a person can press. It fails when one shows no yellow.
