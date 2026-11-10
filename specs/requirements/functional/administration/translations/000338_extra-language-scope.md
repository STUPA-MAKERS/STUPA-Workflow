---
id: "000338"
title: A text without the extra language falls back to English
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/translations/service.py
  - backend/app/modules/notifications/templating.py
scope:
  - backend/app/modules/translations
  - frontend/src/app/core/i18n
---

# A text without the extra language falls back to English

A mail template, a form label, a flow label, a Gremium name, a role name and a branding text
can hold a text in an extra language (000136). When such a value has no text in the language
of the reader, the reader must get the English text. Without an English text, the reader must
get the German text.

Reason: An admin translates the content step by step. A reader of an extra language must not
see an empty label in the meantime.
