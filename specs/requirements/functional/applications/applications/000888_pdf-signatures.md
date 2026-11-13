---
id: "000888"
title: The Antrag PDF of an Antragsart can end with a signature section
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
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

An Antragsart must have a switch "Unterschriften im PDF". The switch is off for a new and for an
existing Antragsart. A person with the right to manage the Antragsarten sets it on the page of the
Antragsart, next to the budget switch.

While the switch is on, the Antrag PDF (000880) of this Antragsart must end with one more table
"Unterschriften" in the design of the other tables (000881). It has two rows:

1. "Sachlich richtig", signed by "Finanzreferent:in".
2. "Ausführungsermächtigt", signed by "Haushaltsbeauftragte:r".

The value cell of each row must be empty room to sign by hand, with a line for the date and a line
for the signature below it. The caption of the signature line names the signer. A row must not
break across two pages.

The Antrag as an Anlage of a protocol (000884) must not have the signature section.

Reason: The Finanzreferat signs a printed Antrag before it pays. The print must give room for the
two signatures, and only the Antragsarten that lead to a payment need them. The Anlage is part of
a signed protocol and is not the paper that the Finanzreferat signs.

Test: Unit test of the Markdown builder: with the switch the document ends with the two signature
rows, without it there is none. Unit test of the typst converter: a signature row is a field row
with the signer. Integration test of the render: the two captions are in the PDF. Integration
test of the admin API: the switch saves and reads back. Integration test of the Anlage: no
signature section.
