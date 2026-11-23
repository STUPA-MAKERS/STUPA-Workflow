---
id: "002520"
title: A file is filed only once
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_a_final_protocol_is_filed_once_in_both_variants"
implementation:
  - backend/app/modules/paperless/filings.py
  - backend/app/modules/paperless/models.py
scope:
  - backend/app/
  - frontend/src/app/
---

# A file is filed only once

The platform must store the number of the Paperless document for each file that it files. The
platform must not file a file that has a stored number or an open job.

Reason: A retry or a second event must not make a second document of the same file.

Test: A unit test runs the filing job two times for one file and expects one upload.
