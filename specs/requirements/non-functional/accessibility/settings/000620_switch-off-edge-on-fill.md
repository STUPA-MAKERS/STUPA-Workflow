---
id: "000620"
title: In very high contrast, a switch, a checkbox and a radio button are filled only when on
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:switchOffEdgeOnFill"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
  - frontend/vendor/ui-kit/src/styles/_check.scss
  - frontend/vendor/ui-kit/src/lib/switch/switch.component.scss
  - frontend/vendor/ui-kit/src/lib/filter-select/filter-select.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# In very high contrast, a switch, a checkbox and a radio button are filled only when on

While "Sehr hoher Kontrast" is on, a switch, a checkbox and a radio button that are off must have
a black fill and a 2 px yellow edge. The knob of a switch that is off must be yellow and on the
left. When on, each must have a yellow fill: the switch with a black knob on the right, the
checkbox with a black tick, the radio button with a black dot. A checkbox that a component draws
itself must look the same.

Reason: A switch that is yellow in both states shows its state only by the place of the knob. The
fill shows the state in the same way as a chosen control (000615).

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts` expects different fills for the
off state and the on state of the switch and of the check box tokens.
