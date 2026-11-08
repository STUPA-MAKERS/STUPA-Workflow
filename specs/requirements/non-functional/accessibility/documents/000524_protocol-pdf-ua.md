---
id: "000524"
title: The protocol PDF is tagged as PDF/UA-1
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "typst/tests/test_compiler.py:test_compile_enforces_pdf_ua_1"
  - "typst/tests/test_integration.py:test_protocol_is_pdf_ua_1_with_title_and_language"
  - "typst/tests/test_integration.py:test_decorative_image_and_formula_pass_pdf_ua"
  - "typst/tests/test_integration.py:test_skipped_heading_level_keeps_the_top_numbers"
implementation:
  - typst/typst_service/compiler.py
  - typst/template/protocol.typ
scope:
  - typst/typst_service
  - typst/template
---

# The protocol PDF is tagged as PDF/UA-1

The typst service must make the protocol PDF with `--pdf-standard ua-1`. The PDF must have
a title and a language.

Reason: A protocol is public, so § 10 L-BGG applies to it. A tagged PDF lets a screen reader
read the structure.
