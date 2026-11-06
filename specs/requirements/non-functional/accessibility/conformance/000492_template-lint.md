---
id: "000492"
title: The template lint has the accessibility rules
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/eslint.config.js
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The template lint has the accessibility rules

The ESLint configuration must enable every rule of
`@angular-eslint/template/accessibility` with the level `error`.

Reason: The lint finds a missing label or a click on a `div` before review.

Test: `npm run lint`.
