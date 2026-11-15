---
id: "000966"
title: An attachment in a blackout block stays out of the public protocol
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/shared/blackout.py
  - backend/app/modules/protocol/public.py
  - backend/app/modules/protocol/service.py
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
