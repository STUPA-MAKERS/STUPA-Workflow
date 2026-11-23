---
id: "002532"
title: An erasure names the filed Paperless documents
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/privacy/test_privacy_paperless.py:test_the_erasure_of_an_antrag_lists_its_paperless_documents"
  - "backend/tests/integration/modules/privacy/test_privacy_paperless.py:test_the_erasure_of_an_account_lists_the_documents_of_its_antraege"
  - "frontend/src/app/pages/admin/privacy/privacy.component.spec.ts:PrivacyComponent"
implementation:
  - backend/app/modules/privacy/paperless.py
  - backend/app/modules/privacy/router.py
  - frontend/src/app/pages/admin/privacy/privacy.component.ts
scope:
  - backend/app/
  - frontend/src/app/
---

# An erasure names the filed Paperless documents

The erasure of an Antrag or of a person must list each Paperless document that the platform
filed for the erased data, with its number and its link. The admin who does the erasure must
see the list. The platform must not delete these documents (002522).

Reason: A copy in Paperless stays after the anonymization in the platform. A person must
decide on each document there, because a document can have a retention duty.

Test: A unit test erases an Antrag with a filed document and expects the document in the
list.
