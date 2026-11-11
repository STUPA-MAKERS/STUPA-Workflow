---
id: "000616"
title: In very high contrast, the navigation has yellow text and yellow icons
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:navigationYellowText"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# In very high contrast, the navigation has yellow text and yellow icons

While "Hoher Kontrast" is on, each entry of the navigation rail and of the bottom bar must
have yellow text and a yellow icon without an edge. This includes "Suche", "Hilfe", "Mehr" and the
account button. The current entry must keep its yellow filled pill with a black icon. The entries
of the "Mehr" sheet follow the same rule, and its current entry must be yellow filled with black
text and a black icon (000615).

Reason: A navigation entry is a control (000614). An edge around each of twelve entries makes the
rail hard to read.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts` expects the yellow text colour
on the entries of the rail and of the bottom bar.
