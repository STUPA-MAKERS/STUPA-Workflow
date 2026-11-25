---
id: "002535"
title: The attachments of an Antrag are filed with its PDF
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
tests:
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_a_decided_antrag_is_filed_with_its_clean_attachments"
implementation:
  - backend/app/modules/paperless_filing/sources.py
  - backend/app/modules/paperless_filing/files.py
scope:
  - backend/app/
---

# The attachments of an Antrag are filed with its PDF

When the platform files the PDF of an Antrag (003110), it must also file each attachment of
that Antrag as a document of its own. The platform must file only an attachment whose virus
scan is clean. Each attachment document must carry the data of 002519, with the title of the
Antrag and the file name as its title.

Reason: The attachments are a part of the Antrag that the Gremium decided. The archive must
hold the whole Antrag.

Test: A unit test moves an Antrag with two clean attachments and one unscanned attachment into
an end state and expects three jobs.
