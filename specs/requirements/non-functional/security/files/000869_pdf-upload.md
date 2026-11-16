---
id: "000869"
title: An embedded PDF is checked on upload
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/unit/modules/media/test_media_documents.py:test_check_refuses_no_pdf_a_broken_and_an_encrypted_pdf"
  - "backend/tests/unit/modules/media/test_media_documents.py:test_check_refuses_more_than_the_page_limit"
  - "backend/tests/unit/modules/media/test_media_documents.py:test_upload_scans_before_pypdf_reads"
  - "backend/tests/unit/modules/media/test_media_documents.py:test_upload_refusals_map_to_415_and_413"
  - "backend/tests/unit/modules/media/test_media_documents.py:test_upload_route_415_and_413"
  - "backend/tests/unit/modules/media/test_media_documents.py:test_download_is_an_attachment_and_inline_is_framable"
implementation:
  - backend/app/modules/media/documents.py
  - backend/app/modules/media/service.py
  - backend/app/modules/media/router.py
  - deploy/web/nginx.conf
scope:
  - backend/app/modules/media
  - backend/app/modules/files
---

# An embedded PDF is checked on upload

The upload of an embedded PDF (000862) must accept only a PDF by its content (libmagic). It
must scan the bytes with ClamAV before the server reads them. It must refuse an encrypted PDF
and a PDF that the server cannot read. A PDF must be at most 20 MiB and at most 100 pages. The
download must stream through the API with the headers of an attachment PDF and never use a
presigned URL.

Reason: A PDF cannot be re-encoded like an image (000344), so the upload must check it before
it is stored.

Test: Unit tests of the upload route: a non-PDF gives 415, an encrypted PDF gives 415, and a
PDF over the limits gives 413.
