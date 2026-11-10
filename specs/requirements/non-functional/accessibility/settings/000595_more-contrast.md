---
id: "000595"
title: More contrast raises the contrast of text and borders
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:moreContrast"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# More contrast raises the contrast of text and borders

With `prefers-contrast: more`, or with the switch "Mehr Kontrast" on, every text must have a
contrast of at least 7:1 to its background, and every border and control edge at least
4.5:1. The focus ring must be 3 px wide. This applies in both themes.

Reason: WCAG 1.4.6. A person with low vision needs more contrast than the 4.5:1 of 000499.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts`.
