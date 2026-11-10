---
id: "000615"
title: In very high contrast, the chosen control of a choice is yellow filled
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:chosenIsYellowFill"
  - "frontend/src/app/shared/very-high-contrast.styles.spec.ts:permissionChips"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
  - frontend/vendor/ui-kit/src/styles/_very-high.scss
  - frontend/src/app/shared/ui/_very-high-contrast.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# In very high contrast, the chosen control of a choice is yellow filled

While "Sehr hoher Kontrast" is on, the chosen control of a choice must have a yellow fill and
black text. Each other control of the same choice must have a black fill, yellow text and a 2 px
yellow edge. This applies to a segmented control, a tab bar, a group of filter chips, a group of
choice chips and a stepper. A toggle button and the button of an open menu are a choice of two
states: pressed or open is yellow filled, the other state has the yellow edge.

Reason: One picture for the chosen state lets a person read each choice the same way. The yellow
fill is the strongest mark, so it shows the choice.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts` expects the fill for the chosen
state and the edge for the other state in each listed control.
