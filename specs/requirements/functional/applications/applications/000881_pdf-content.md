---
id: "000881"
title: The Antrag PDF shows the Antrag like the detail page
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
implementation:
  - backend/app/modules/applications/pdf.py
  - frontend/src/app/pages/applications
scope:
  - backend/app/modules/applications
  - backend/app/modules/pdf
  - typst
  - frontend/src/app/pages/applications
---

# The Antrag PDF shows the Antrag like the detail page

The Antrag PDF must use the design of the protocol PDF from the typst service and must be
tagged as PDF/UA-1 (000524). It must hold, in this order:

1. The head data: title, Antragsart, Gremium, status, date of receipt, applicant and the
   version number.
2. The answers of the form, with one heading per section of the form, in the order of the
   form. A field that is not visible (`visibleIf`) must not show.
3. The Kostenaufstellung as a table with the total, if the form has one.
4. The names of the attached files, without the files.
5. The valid decision with the approved amount and the conditions, if the Antrag has one.

The PDF must not show comments and must not show the status history.

Reason: The PDF must show the Antrag as the Gremium reads it. Attached files often hold
personal data that the platform cannot black out, so only their names go into the PDF.

Test: Unit test of the Markdown builder: a fixture Antrag gives the five parts in order, and
a hidden field does not show.
