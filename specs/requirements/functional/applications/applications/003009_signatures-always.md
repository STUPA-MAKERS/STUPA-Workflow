---
id: "003009"
title: The Antrag PDF always ends with the signature rows of its Antragsart
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "backend/tests/unit/modules/documents/test_application_markdown.py:test_signature_rows"
  - "backend/tests/integration/modules/protocol/test_protocol_application_anlage.py:test_the_protocol_appends_the_antrag_as_it_was_at_the_close_of_the_top"
implementation:
  - backend/app/modules/documents/service.py
  - backend/migrations/versions/e7a4c2d9f150_drop_application_type_pdf_signatures.py
  - frontend/vendor/ui-kit/views/form-editor/src/form-editor-view.component.html
scope:
  - backend/app/modules/application_types
  - backend/app/modules/admin
  - backend/app/modules/documents
  - frontend/src/app/pages/admin/forms
  - mcp
---

# The Antrag PDF always ends with the signature rows of its Antragsart

An Antragsart must not have the switch "Unterschriften im PDF". The Antrag PDF (000880) must end
with the signature section of 000888 whenever the list of signature rows of 003005 of its
Antragsart has a row, in every status of the Antrag. The Antrag as an Anlage of a protocol (000884)
must have the same signature section. An Antragsart with an empty list gives no signature section.

The page of the Antragsart must always show the list of signature rows. This spec replaces the
switch of 000888 and of 003005 and the rule of 000888 that the Anlage has no signature section.

Reason: The finance officer signs every printed Antrag, also the one in the protocol. The list of
rows alone tells which signatures an Antragsart needs, so a second switch only hides them by
mistake.

Test: A unit test of the Markdown builder writes the configured rows in order. An integration
test renders the Anlage of an Antrag whose Antragsart has rows and finds the signature section.
