---
id: "000862"
title: A protocol text embeds a PDF
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/unit/modules/media/test_media_documents.py:test_upload_route_201_for_a_writer"
  - "backend/tests/unit/modules/media/test_media_documents.py:test_upload_route_refuses_who_cannot_write"
  - "backend/tests/unit/modules/media/test_media_documents.py:test_document_ids_come_in_the_order_of_the_first_reference"
  - "frontend/src/app/features/meetings/top-sheet/top-sheet.component.spec.ts:TopSheetComponent"
implementation:
  - backend/app/modules/media/refs.py
  - backend/app/modules/media/service.py
  - backend/app/modules/protocol/documents_router.py
  - frontend/vendor/ui-kit/markdown-editor/src/document.extension.ts
  - frontend/vendor/ui-kit/markdown-editor/src/markdown-editor.component.ts
  - frontend/src/app/features/meetings/top-sheet/top-sheet.component.ts
scope:
  - backend/app/modules/media
  - backend/app/modules/protocol
  - frontend/src/app/shared/markdown
  - frontend/src/app/features/meetings
  - frontend/vendor/ui-kit/markdown-editor
---

# A protocol text embeds a PDF

The Markdown of a protocol must embed an uploaded PDF as
`[<file name>](/api/media/documents/<uuid>)`. This must work in each Markdown text of a
protocol: the TOP texts and the free protocol text. The editor must insert the reference on a
paste, on a drop and from the insert button, the same way as an image (000506). Only a person
who can write the text must be able to upload a PDF.

Reason: A Sitzung often treats a document, for example a Haushaltsplan or an offer. The
document belongs to the record of the Sitzung at the place where the Sitzung treats it.

Test: Unit tests of the upload route, of the reference parser and of the editor insert.
