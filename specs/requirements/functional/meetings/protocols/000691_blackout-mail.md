---
id: "000691"
title: A marked segment sends the public PDF to the mailing list
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "backend/tests/integration/modules/protocol/test_protocol_blackout.py:test_finalize_with_a_mark_mails_the_public_pdf"
implementation:
  - backend/app/modules/protocol/service.py
scope:
  - backend/app/modules/protocol
  - backend/worker/protocol.py
---

# A marked segment sends the public PDF to the mailing list

If a protocol has a marked segment, the finalize must render the internal PDF and the public
PDF, as for a non-public TOP (000355). Only the public PDF must go to the mailing list.

Reason: The mailing list holds extra addresses outside the Gremium.

Test: A backend test finalizes a protocol with a marker and checks the PDF of the mail.
