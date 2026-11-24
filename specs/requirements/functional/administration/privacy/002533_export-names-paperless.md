---
id: "002533"
title: The data export names the filed Paperless documents
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/privacy/test_auskunft_completeness_unit.py:test_build_workbook_names_the_paperless_documents"
  - "backend/tests/integration/modules/privacy/test_privacy_paperless.py:test_the_data_export_names_the_paperless_documents"
implementation:
  - backend/app/modules/privacy/paperless.py
  - backend/app/modules/privacy/service.py
scope:
  - backend/app/
---

# The data export names the filed Paperless documents

The data export of a person (000458) must name each Paperless document that the platform filed
for an Antrag of that person, with its number and the date of the filing.

Reason: The person has the right to learn where copies of the personal data are.

Test: A unit test exports the data of a person with a filed Antrag and expects the document
number in the workbook.
