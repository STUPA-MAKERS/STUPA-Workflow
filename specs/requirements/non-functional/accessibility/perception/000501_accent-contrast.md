---
id: "000501"
title: An admin accent colour keeps the contrast
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - backend/app/modules/admin
---

# An admin accent colour keeps the contrast

The branding page must refuse an accent colour that gives less than 4.5:1 for text on the
accent or for the accent on the surfaces. The check must use both themes.

Reason: An admin sets the accent colour, so the tokens alone cannot keep WCAG 1.4.3.
