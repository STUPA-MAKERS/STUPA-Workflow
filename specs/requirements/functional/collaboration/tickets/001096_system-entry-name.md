---
id: "001096"
title: A system entry names the short name
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/core/i18n/i18n.service.spec.ts:I18nService"
implementation:
  - frontend/src/app/core/i18n/i18n.service.ts
  - frontend/src/app/core/branding/branding.service.ts
  - frontend/src/app/core/i18n/catalog/de.json
scope:
  - frontend/src/app/core/i18n
  - frontend/src/app/core/branding
  - frontend/src/app/features/todos
  - frontend/src/app/pages/tickets
---

# A system entry names the short name

An entry without a person in the history of a ticket or a to-do card must show the short
name of the active branding. A UI text must reach the short name as the placeholder
`{shortName}` without a param.

Reason: The platform makes these entries, so they must carry the name of the platform. The
placeholder lets an admin text use the name too.

Test: A frontend test translates a system entry before and after a change of the short name.
