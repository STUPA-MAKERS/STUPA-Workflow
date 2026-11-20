---
id: "001803"
title: The empty-state face has room above and below
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.spec.ts:EmptyStateComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The empty-state face has room above and below

The face of an empty state (spec 001360) must have 3rem of room above it and 3rem below its
hint. A page must not add more room around an empty state, so the room is not doubled (for
example in the day list of the Kalender).

Reason: In a tall tile or a sheet the face stuck to the head of the surface.
