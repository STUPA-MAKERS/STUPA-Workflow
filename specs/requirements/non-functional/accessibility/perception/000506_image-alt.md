---
id: "000506"
title: A Markdown image has an alternative text
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/src/app/shared/markdown/image-alt.service.spec.ts:ImageAltService"
  - "frontend/src/app/shared/markdown/markdown-image-upload.directive.spec.ts:MarkdownImageUploadDirective"
implementation:
  - frontend/src/app/shared/markdown/image-alt.service.ts
  - frontend/src/app/shared/markdown/image-alt-dialog.component.ts
  - frontend/src/app/shared/markdown/markdown-image-upload.directive.ts
  - frontend/src/app/features/meetings/top-sheet/top-sheet.component.ts
  - typst/template/protocol.typ
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - typst/template
---

# A Markdown image has an alternative text

The Markdown editor must ask for an alternative text when a user adds an image. A user can
mark the image as decorative, then the alternative text is empty. The protocol PDF must use
the same text.

Reason: WCAG 1.1.1. A screen reader reads the alternative text instead of the image.
