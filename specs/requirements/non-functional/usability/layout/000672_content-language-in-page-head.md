---
id: "000672"
title: The language of a content editor stands in the page head
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/src/app/pages/admin/branding/branding-editor.component.spec.ts:BrandingEditorComponent"
  - "frontend/src/app/pages/admin/mail-templates/mail-templates.component.spec.ts:MailTemplatesComponent"
implementation:
  - frontend/src/app/pages/admin/roles
  - frontend/src/app/pages/admin/branding
  - frontend/src/app/pages/admin/mail-templates
  - frontend/src/app/shared/ui/content-lang-switch
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The language of a content editor stands in the page head

A page of Verwaltung that edits texts in more than one language must show the language picker
at the end of the page head, beside the title. This applies to Rollen & Rechte, Texte,
E-Mail-Vorlagen and the form editor. On the page Übersetzungen the language is a filter of
the list and stays a filter chip.

Reason: The picker stands in four different places. The person finds it in one place on
every page.

Test: A unit test of the pages Texte and E-Mail-Vorlagen expects the language picker inside
the page head.
