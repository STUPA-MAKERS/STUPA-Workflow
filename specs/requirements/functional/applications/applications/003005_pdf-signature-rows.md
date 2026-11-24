---
id: "003005"
title: The signature rows of the Antrag PDF are a setting of the Antragsart
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "backend/tests/unit/modules/documents/test_application_markdown.py:test_signature_rows"
  - "backend/tests/integration/admin/test_application_types.py:test_signature_rows"
implementation:
  - backend/app/modules/application_types/models.py
  - backend/app/modules/admin/service/application_types.py
  - backend/app/modules/documents/application_markdown.py
  - frontend/src/app/pages/admin/forms
scope:
  - backend/app/modules/application_types
  - backend/app/modules/admin
  - backend/app/modules/documents
  - frontend/src/app/pages/admin/forms
  - mcp
---

# The signature rows of the Antrag PDF are a setting of the Antragsart

An Antragsart must hold a list of signature rows. Each row has a label and a signer, for example
"Sachlich richtig" and "Finanzreferent:in". The signature section of 000888 must show exactly
these rows, in this order. While the switch "Unterschriften im PDF" is on, the page of the
Antragsart must show the list, and the person can add, edit, move and remove a row. The code must
not hold a label or a signer.

The migration must give each existing Antragsart the two rows that the PDF shows today, so an
existing PDF does not change. A new Antragsart starts with an empty list. With the switch on and
an empty list the PDF has no signature section.

Reason: The labels and the signers depend on the finance rules of one student body. Another
student body or a changed rule needs other rows.

Test: A unit test of the Markdown builder writes the configured rows in order. An integration
test of the admin API saves and reads back the rows. A migration test finds the two rows at an
existing Antragsart.
