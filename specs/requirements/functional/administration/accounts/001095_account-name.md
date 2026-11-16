---
id: "001095"
title: The account on the login names the short name
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/core/i18n/i18n.service.spec.ts:I18nService"
  - "frontend/src/app/core/branding/branding.service.spec.ts:BrandingService"
implementation:
  - frontend/src/app/core/i18n/catalog/de.json
  - frontend/src/app/core/i18n/catalog/en.json
scope:
  - frontend/src/app/core/i18n
  - frontend/src/app/pages/login
  - frontend/src/app/pages/home.component.html
---

# The account on the login names the short name

The login page and the start page must name the account of the platform as
"<Kurzname>-Konto", with the short name of the active branding.

Reason: The account belongs to the platform, so its name must change with the name of the
platform.

Test: Frontend tests translate the account name before and after a branding load.
