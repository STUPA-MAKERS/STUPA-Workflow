---
id: "000867"
title: The PDF of a non-public TOP stays internal
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/unit/modules/media/test_media_documents.py:test_public_document_ids_leave_out_a_non_public_top"
  - "backend/tests/unit/modules/media/test_media_documents.py:test_public_download_only_for_a_pdf_of_the_public_text"
implementation:
  - backend/app/modules/protocol/public.py
  - backend/app/modules/protocol/public_images_router.py
  - frontend/src/app/features/public-protocols/public-protocol-detail.component.ts
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/public-protocols
---

# The PDF of a non-public TOP stays internal

The public PDF (000355) and the public protocol page must hold only the embedded PDFs of
public texts. An embedded PDF of a non-public TOP must not be an Anlage of the public PDF, and
its public download must answer 404. The public PDF must number its own Anlagen from 1.

Reason: A non-public TOP often treats a document with personal or internal data.

Test: Unit tests of the public render input and of the public PDF download route.
