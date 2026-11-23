---
id: "002516"
title: A final protocol is filed in Paperless
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_a_final_protocol_is_filed_once_in_both_variants"
implementation:
  - backend/app/modules/paperless_filing/sources.py
  - backend/app/modules/paperless_filing/files.py
  - backend/worker/paperless.py
scope:
  - backend/app/
  - frontend/src/app/
---

# A final protocol is filed in Paperless

When a protocol becomes final, the platform must file its internal PDF in Paperless. When the
protocol has a public PDF, the platform must file that PDF as a second document.

Reason: Each file that the platform generates belongs in the archive, without an action of a
person.

Test: A unit test finalizes a protocol and expects one job for each PDF.
