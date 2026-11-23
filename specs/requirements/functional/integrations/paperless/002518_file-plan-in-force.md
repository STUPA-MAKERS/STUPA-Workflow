---
id: "002518"
title: A Haushaltsplan is filed when it comes into force
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_a_plan_in_force_is_filed"
implementation:
  - backend/app/modules/paperless_filing/sources.py
  - backend/app/modules/paperless_filing/files.py
scope:
  - backend/app/
  - frontend/src/app/
---

# A Haushaltsplan is filed when it comes into force

When a version of a Haushaltsplan comes into force, the platform must file the PDF of that
version in Paperless. The download of the export must not file a document.

Reason: The version in force is the basis of each booking of its Haushaltsjahr. A draft is not
a document of the archive.

Test: A unit test brings a version into force and expects one job.
