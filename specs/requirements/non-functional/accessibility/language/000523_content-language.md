---
id: "000523"
title: Content in a different language has its lang
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/src/app/shared/forms/i18n-text.spec.ts:resolvedI18nLang"
  - "frontend/src/app/shared/forms/formly-mapper.spec.ts:FormTextLanguage"
  - "frontend/src/app/shared/forms/answer-view/answer-view.component.spec.ts:AnswerViewComponent"
  - "frontend/src/app/features/public-protocols/public-protocol-detail.component.spec.ts:PublicProtocolDetailComponent"
  - "frontend/vendor/ui-kit/src/lib/text-lang.spec.ts:textLang"
  - "backend/tests/unit/modules/protocol/test_public_protocols_unit.py:test_get_protocol_hides_non_public_content"
implementation:
  - frontend/src/app/shared/forms/i18n-text.ts
  - frontend/src/app/shared/forms/formly-mapper.ts
  - frontend/src/app/shared/forms/answer-view/answer-view.component.ts
  - frontend/src/app/pages/applications/applications-detail.component.ts
  - frontend/src/app/features/public-protocols/public-protocol-detail.component.ts
  - backend/app/modules/protocol/public.py
  - frontend/vendor/ui-kit/src/lib/field-group/field-group.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Content in a different language has its lang

Content that shows in a language different from the UI language must have its own `lang`
attribute. This applies to Antrag content, form texts and protocol text.

Reason: WCAG 3.1.2. Without it, a screen reader reads English text with a German voice.
