---
id: "000950"
title: The draft of a protocol reads as a PDF after the meeting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/protocol/test_protocol_draft_and_approval.py:test_draft_pdf_gives_both_variants_and_stores_nothing"
  - "backend/tests/integration/modules/protocol/test_protocol_draft_and_approval.py:test_draft_pdf_route_needs_a_draft_and_a_render_service"
  - "frontend/src/app/features/meetings/protocol-bar/protocol-bar.component.spec.ts:draftPdf"
implementation:
  - backend/app/modules/protocol/draft_mail.py
  - backend/app/modules/protocol/router.py
  - frontend/src/app/features/meetings/protocol-bar/protocol-bar.component.ts
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
---

# The draft of a protocol reads as a PDF after the meeting

Each person who can read a meeting must be able to download the PDF of its draft protocol in
two variants: the internal one and the public one. Each page of this PDF must have the
watermark "Entwurf" (000925). The download must not store a PDF and must not change the
protocol. The download must be refused while the meeting is live. The protocol bar must
show the two links while the protocol is a draft.

Reason: The members and the keeper must see the internal and the public result before the
finalization, because a finalized protocol goes to the members by mail and changes only on the way back to
the draft (000983). A draft from a live Sitzung is not
complete.

Test: An integration test that reads both variants of a draft, finds no stored PDF and gets
a 409 for a live meeting, and a frontend unit test that finds the two links in the bar of a
draft.
