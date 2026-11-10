---
id: "000635"
title: A page with Speichern offers Verwerfen in its header
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/pages/admin/login-settings/login-settings.component.spec.ts:LoginSettingsComponent"
  - "frontend/src/app/pages/admin/deadlines/deadlines.component.spec.ts:AdminDeadlinesComponent"
  - "frontend/src/app/pages/admin/notifications/notification-settings.component.spec.ts:NotificationSettingsComponent"
  - "frontend/src/app/pages/admin/mail-templates/mail-templates.component.spec.ts:MailTemplatesComponent"
  - "frontend/src/app/pages/admin/privacy/privacy.component.spec.ts:PrivacyComponent"
  - "frontend/src/app/pages/admin/roles/roles.component.spec.ts:AdminRolesComponent"
  - "frontend/src/app/pages/admin/branding/branding-editor.component.spec.ts:BrandingEditorComponent"
  - "frontend/src/app/pages/admin/flow/flow-editor.component.spec.ts:FlowEditorComponent"
  - "frontend/src/app/pages/admin/forms/form-editor.component.spec.ts:FormEditorComponent"
implementation:
  - frontend/src/app/pages/admin/login-settings/login-settings.component.ts
  - frontend/src/app/pages/admin/deadlines/deadlines.component.ts
  - frontend/src/app/pages/admin/notifications/notification-settings.component.ts
  - frontend/src/app/pages/admin/mail-templates/mail-templates.component.ts
  - frontend/src/app/pages/admin/privacy/privacy.component.ts
  - frontend/src/app/pages/admin/roles/roles.component.ts
  - frontend/src/app/pages/admin/branding/branding-editor.component.ts
  - frontend/src/app/pages/admin/flow/flow-editor.component.ts
  - frontend/src/app/pages/admin/forms/form-editor.component.ts
scope:
  - frontend/src/app/pages/admin
---

# A page with Speichern offers Verwerfen in its header

A page of Verwaltung that shows the floating "Speichern" (`NF/usability/layout/000198`) must
show "Verwerfen" as a text button on the title row while there are unsaved changes.
"Verwerfen" must set every field back to the saved value and must then hide together with
"Speichern". It is the one action of the header (`NF/usability/layout/000197`). On a page whose
header holds tools (Rollen & Rechte, Flow-Editor, Formular-Editor) it is the first of them,
and on a phone the two editors show it in the menu of the header.

Reason: A user who changes a field by mistake needs a way back that does not lose the place
on the page. Without "Verwerfen" the only way back is to load the page again.

Test: A unit test of each settings page changes a field, expects "Verwerfen" and
"Speichern", activates "Verwerfen" and expects the saved value and neither button.
