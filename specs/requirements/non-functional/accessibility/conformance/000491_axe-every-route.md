---
id: "000491"
title: Every route passes an axe check in both themes
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/src/app/axe-routes.contract.spec.ts:axeRouteSweep"
implementation:
  - frontend/e2e/06-axe.spec.ts
  - frontend/e2e/axe-routes.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - frontend/e2e
---

# Every route passes an axe check in both themes

The e2e suite must run axe-core on every route, in the light theme and in the dark theme.
The check must use the tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa` and `wcag22aa`. A
violation must fail the suite.

Reason: jsdom cannot compute contrast or layout, so only a real browser finds these errors.

Test: `frontend/e2e/` with `@axe-core/playwright`.
