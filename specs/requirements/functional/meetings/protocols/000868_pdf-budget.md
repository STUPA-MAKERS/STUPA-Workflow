---
id: "000868"
title: A protocol holds at most 20 Anlagen
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/unit/modules/media/test_media_documents.py:test_render_documents_keep_the_order_and_the_budget"
  - "backend/tests/unit/modules/media/test_media_documents.py:test_render_documents_never_fail_for_a_missing_pdf"
  - "typst/tests/test_appendix.py:test_a_missing_or_unreadable_pdf_or_one_past_the_budget_is_no_anlage"
implementation:
  - backend/app/modules/media/service.py
  - typst/typst_service/appendix.py
scope:
  - backend/app/modules/protocol
  - backend/app/modules/media
---

# A protocol holds at most 20 Anlagen

A protocol PDF must hold at most 20 Anlagen and at most 300 Anlage pages in total. An embedded
PDF over this limit, or one that is missing, must not be an Anlage. Its place must print
`Anlage nicht eingebunden: <file name>`. An embedded PDF must never make the render fail.

Reason: The typst service has fixed memory and time. A finalize must not stop because of one
document.

Test: Unit test of the render input: the 21st PDF is left out and its place has the text.
