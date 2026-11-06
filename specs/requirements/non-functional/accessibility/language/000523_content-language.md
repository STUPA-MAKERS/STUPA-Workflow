---
id: "000523"
title: Content in a different language has its lang
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Content in a different language has its lang

Content that shows in a language different from the UI language must have its own `lang`
attribute. This applies to Antrag content, form texts and protocol text.

Reason: WCAG 3.1.2. Without it, a screen reader reads English text with a German voice.
