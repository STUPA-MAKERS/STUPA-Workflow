---
id: "000864"
title: The protocol PDF appends each embedded PDF as an Anlage
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "typst/tests/test_appendix.py:test_number_documents_follows_the_first_reference"
  - "typst/tests/test_appendix.py:test_merge_puts_each_page_under_its_anlage_page_as_an_artifact"
  - "typst/tests/test_integration.py:test_embedded_pdfs_become_watermarked_anlagen_with_linked_references"
implementation:
  - typst/typst_service/appendix.py
  - typst/typst_service/document.py
  - typst/template/protocol.typ
  - backend/app/modules/protocol/service.py
scope:
  - backend/app/modules/protocol
  - backend/app/modules/media
  - typst/
---

# The protocol PDF appends each embedded PDF as an Anlage

The protocol PDF must append each embedded PDF (000862) after the signatures as an Anlage.
The Anlagen must have the numbers 1, 2, 3 in the order of their first reference. A PDF that
the text references two times must be one Anlage. Each page of an Anlage must be one page of
the protocol PDF and must keep its size and orientation.

Reason: The mailing list and the archive get one file. That file must hold the full record of
the Sitzung.

Test: Integration test of the typst service: a protocol with two references to one PDF and one
reference to a second PDF gives two Anlagen with all their pages.
