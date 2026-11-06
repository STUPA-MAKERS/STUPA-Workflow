---
id: "000338"
title: Extra languages cover only UI texts
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/translations
  - frontend/src/app/core/i18n
scope:
  - backend/app/modules/translations
  - frontend/src/app/core/i18n
---

# Extra languages cover only UI texts

Mail templates, form labels and branding texts must know German and English only. With an extra
language, they must show in English.
