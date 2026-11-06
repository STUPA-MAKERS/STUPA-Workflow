---
id: "000337"
title: A new language starts inactive
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

# A new language starts inactive

A new UI language must stay inactive until an admin activates it. Only an active language must
show in the language switch. The delete of a language must remove its overrides.
