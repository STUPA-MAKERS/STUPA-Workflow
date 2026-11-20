---
id: "000501"
title: An admin accent colour keeps the contrast
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/pages/admin/branding/branding-editor.component.spec.ts:BrandingEditorComponent"
implementation:
  - frontend/src/app/core/theme/accent.ts
  - frontend/src/app/pages/admin/branding/branding-editor.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - backend/app/modules/admin
---

# An admin accent colour keeps the contrast

The branding page must refuse an accent colour that the accent check of the kit refuses
(ui-kit:002286).

Reason: An admin sets the accent colour, so the tokens alone cannot keep WCAG 1.4.3.
