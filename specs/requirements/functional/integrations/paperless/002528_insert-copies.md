---
id: "002528"
title: An insert from Paperless copies the document as an embedded PDF
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_an_insert_copies_the_document_as_an_embedded_pdf"
  - "backend/tests/unit/modules/paperless/test_client.py:test_download_answers_the_pdf_and_refuses_a_file_over_the_limit"
  - "frontend/src/app/features/meetings/paperless-insert/paperless-insert.component.spec.ts:PaperlessInsertComponent"
implementation:
  - backend/app/modules/protocol/documents_router.py
  - backend/app/modules/paperless/client.py
  - backend/app/modules/media/models.py
  - frontend/src/app/features/meetings/paperless-insert/paperless-insert.component.ts
scope:
  - backend/app/
  - frontend/src/app/
---

# An insert from Paperless copies the document as an embedded PDF

A pick in the Paperless search (002534) must copy the PDF version of the document from Paperless into the
platform. The copy must pass each check of a PDF upload (NF/security/files/000869). The editor
must insert it as an embedded PDF (000862) with the title of the document as its name. The
platform must store the number of the Paperless document with the copy.

Reason: A copy is a file of the platform. It follows the read right of its Sitzung and stays
when the document changes in Paperless. The platform then shows no preview from Paperless.

Test: A unit test inserts a document and expects a stored PDF with the document number.
