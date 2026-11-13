---
id: "000866"
title: The place of an embedded PDF links to its Anlage
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "typst/tests/test_integration.py:test_embedded_pdfs_become_watermarked_anlagen_with_linked_references"
implementation:
  - typst/template/protocol.typ
  - typst/typst_service/markdown.py
scope:
  - typst/
---

# The place of an embedded PDF links to its Anlage

At the place of the reference (000862), the protocol PDF must print
`Anlage <N>: <file name> (Seite <P>)`. `<P>` is the number of the first page of the Anlage
in the protocol PDF. The text must be a link to that page.

Reason: A reader of the protocol finds the document from the place where the Sitzung treats
it, with one click.

Test: Integration test of the typst service: the reference text holds the correct page number,
and its link points to the first page of the Anlage.
