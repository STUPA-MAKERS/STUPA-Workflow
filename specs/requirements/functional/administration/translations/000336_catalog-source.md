---
id: "000336"
title: The frontend catalog is the source of UI texts
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/core/i18n/translations.ts
  - backend/app/modules/translations/catalog.py
  - backend/app/modules/translations/service.py
scope:
  - backend/app/modules/translations
  - frontend/src/app/core/i18n
---

# The frontend catalog is the source of UI texts

The built-in UI texts must be only in `catalog/de.json` and `catalog/en.json`. An admin can
override a text and add languages. The database must hold only the overrides.
