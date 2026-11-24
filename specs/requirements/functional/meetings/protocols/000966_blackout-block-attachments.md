---
id: "000966"
title: An attachment in a blackout block stays out of the public protocol
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/shared/test_blackout.py:test_black_out_drops_the_pdf_of_a_block"
  - "backend/tests/integration/modules/protocol/test_protocol_blackout.py:test_public_document_drops_a_block_and_its_pdf"
implementation:
  - backend/app/shared/blackout.py
  - backend/app/modules/protocol/public.py
  - backend/app/modules/protocol/service/document.py
  - backend/app/modules/protocol/service/render.py
scope:
  - backend/app/modules/protocol
  - backend/app/modules/media
---

# An attachment in a blackout block stays out of the public protocol

An embedded PDF (000862) or an image in a blackout block (000965) must not be in the public
variants. The public PDF must not append the PDF as an Anlage and must number its other Anlagen
from 1 (000867). The public download of the PDF and of the image must answer 404. The internal
PDF must append the PDF as an Anlage as usual.

Reason: The document in a blacked-out block is mostly the reason for the blackout, for example
a letter with names or an offer with personal data.

Test: Unit tests of the public render input and of the public download route with a PDF in a
block.
