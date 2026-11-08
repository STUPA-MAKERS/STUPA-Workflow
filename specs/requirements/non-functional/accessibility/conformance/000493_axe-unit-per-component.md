---
id: "000493"
title: Every shared component has a jest-axe test
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/src/app/shared/a11y.contract.spec.ts:sharedComponentAxeContract"
implementation:
  - frontend/src/app/shared/a11y.contract.spec.ts
  - frontend/src/testing/a11y.ts
  - frontend/vendor/ui-kit/testing/a11y.ts
scope:
  - frontend/src/app/shared
  - frontend/vendor/ui-kit
---

# Every shared component has a jest-axe test

Every component in `frontend/src/app/shared/` and in the ui-kit must have a jest-axe test.
The test must render each state of the component and expect no violations.

Reason: A shared component appears on many pages, so one error repeats on each of them.

Test: A contract spec that finds a shared component without `toHaveNoViolations`.
