---
id: "001361"
title: The face of an empty state moves until motion is reduced
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.spec.ts:EmptyStateComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.scss
scope:
  - frontend/vendor/ui-kit/src/lib/empty-state
---

# The face of an empty state moves until motion is reduced

The face of an empty state (001360) must move without end:

- The eyes blink every 3.2 s and glance to the side on a 9.6 s cycle.
- Each dot wobbles by about 0.5 px over 4 s to 7 s and fades smoothly between 30 % and 55 %
  opacity over 5 s to 9 s. Each dot has its own period and delay, so the dots never move in
  step.

With "Weniger Bewegung" on, or with the system setting for reduced motion while the user has no
choice (000219), the face and the dots must stand still. The face has no pause button of its
own, because "Weniger Bewegung" is the way to stop it.

Reason: Small, slow motion makes the empty state feel alive without drawing the eye away from
the page. The setting for less motion already stops every animation of the app, so a second
switch on each empty state would only add noise.

Test: A unit test expects 13 dots, each with its own wobble and flicker period.
