---
id: "000908"
title: The protocol names the kind, the place and the form of the meeting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/unit/modules/protocol/test_protocol_markdown.py:test_header_names_the_kind_the_place_and_the_form"
  - "typst/tests/test_document.py:test_the_header_names_the_kind_the_place_and_the_form"
implementation:
  - backend/app/modules/protocol/markdown.py
  - backend/app/modules/protocol/service/document.py
  - typst/typst_service/document.py
scope:
  - backend/app/modules/protocol
  - typst
---

# The protocol names the kind, the place and the form of the meeting

The header of the protocol PDF must show the kind (000903), the place and the form (000907) of
the meeting. A meeting without a place must show no place line.

Reason: The Geschäftsordnung lists the place and the form as contents of the protocol.

Test: A unit test of the header data of the render call.
