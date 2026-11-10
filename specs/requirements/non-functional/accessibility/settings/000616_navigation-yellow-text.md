---
id: "000616"
title: In very high contrast, the navigation has yellow text and yellow icons
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:navigationYellowText"
implementation:
  - frontend/vendor/ui-kit/shell/src/nav-rail
  - frontend/vendor/ui-kit/shell/src/bottom-bar
  - frontend/vendor/ui-kit/shell/src/account-menu
  - frontend/src/app/features/help/help-menu/help-menu.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# In very high contrast, the navigation has yellow text and yellow icons

While "Sehr hoher Kontrast" is on, each entry of the navigation rail and of the bottom bar must
have yellow text and a yellow icon without an edge. This includes "Suche", "Hilfe", "Mehr" and the
account button. The current entry must keep its yellow filled pill with a black icon.

Reason: A navigation entry is a control (000614). An edge around each of twelve entries makes the
rail hard to read.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts` expects the yellow text colour
on the entries of the rail and of the bottom bar.
