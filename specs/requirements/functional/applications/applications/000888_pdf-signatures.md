---
id: "000888"
title: The Antrag PDF of an Antragsart can end with a signature section
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/documents
  - backend/app/modules/admin
  - frontend/src/app/pages/admin/forms
scope:
  - backend/app/modules/application_types
  - backend/app/modules/admin
  - backend/app/modules/documents
  - typst
  - mcp
  - frontend/src/app/pages/admin/forms
---

# The Antrag PDF of an Antragsart can end with a signature section

The Antrag PDF (000880) can end with one more table "Unterschriften" in the design of the other
tables (000881). Its rows are the signature rows of the Antragsart (003005), and 003009 says when
the PDF has the table.

The value cell of each row must be empty room to sign by hand, with a line for the date and a line
for the signature below it. The caption of the signature line names the signer. A row must not
break across two pages.

Reason: The Finanzreferat signs a printed Antrag before it pays. The print must give room for the
signatures.

Test: Unit test of the Markdown builder: the document ends with the signature rows. Unit test of
the typst converter: a signature row is a field row with the signer. Integration test of the
render: the captions are in the PDF.
