---
id: "000136"
title: Every i18n text is editable in English too
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/pages/admin/translations/translations.component.ts
  - frontend/src/app/pages/admin/forms/form-editor.component.ts
  - frontend/src/app/pages/admin/gremium-roles/gremium-role-dialog.component.ts
scope:
  - backend/app/modules/forms
  - frontend/src/app/pages/admin
---

# Every i18n text is editable in English too

Every editor of an i18n value must edit English too, and every extra UI language. This covers
form labels, flow labels, Gremium names, role names and branding texts.
