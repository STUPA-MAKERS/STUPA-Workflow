---
id: "000522"
title: The page language follows the UI language
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/core/i18n/i18n.service.ts
scope:
  - frontend/src/app/core/i18n
---

# The page language follows the UI language

The `lang` attribute of the `html` element must be the current UI language.

Reason: WCAG 3.1.1. A screen reader picks its voice from this attribute.
