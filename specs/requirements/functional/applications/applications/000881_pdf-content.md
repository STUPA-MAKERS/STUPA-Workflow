---
id: "000881"
title: The Antrag PDF shows the Antrag like the detail page
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
implementation:
  - backend/app/modules/documents
  - frontend/src/app/pages/applications
scope:
  - backend/app/modules/applications
  - backend/app/modules/pdf
  - typst
  - frontend/src/app/pages/applications
---

# The Antrag PDF shows the Antrag like the detail page

The Antrag PDF must use the design of the protocol PDF from the typst service, with the fonts
Blender for headings and DIN for text, and must be tagged as PDF/UA-1 (000524). It must have no
title page: the first page starts with the title of the Antrag at the top of the page, with no
logo above it. The whole Antrag must be in tables of two columns, label and value, drawn like
the table of the Haushaltsplan PDF: a thick rule above and below, a dashed rule between the rows, and
the section name on a grey band across the table. Each value cell must render its Markdown
(paragraphs, lists, emphasis, links, tables).

A value that would take 30 lines or more must show 29 lines and a line "…". A cell of the
Kostenaufstellung (a position or an offer) that would take 3 lines or more must show 2 lines
and a line "…". The Kostenaufstellung must have no rule above and no rule below.

The version, each date, an IBAN and each amount must print in the monospace font. The names of
the attached files must print in the monospace font, one name per line, without list markers.

The PDF must hold, in this order:

1. The head data in one table: Gremium, Antragsart, status, date of receipt, applicant, the
   version number and the names of the attached files (item 4).
2. The answers of the form, one table per section of the form with the section name as its
   heading, one row per field, in the order of the form. A text answer (for example the
   description) is Markdown and renders in its cell. A field that is not visible
   (`visibleIf`) must not show.
3. The Kostenaufstellung as a table with the total, in the row of its field, if the form has
   one.
4. The names of the attached files, without the files.
5. The valid decision with the approved amount and the conditions, if the Antrag has one.

The PDF must not show comments and must not show the status history.

Reason: The PDF must show the Antrag as the Gremium reads it. Attached files often hold
personal data that the platform cannot black out, so only their names go into the PDF.

Test: Unit test of the Markdown builder: a fixture Antrag gives the five parts in order, as
field rows, and a hidden field does not show. Unit test of the typst converter: a field row
keeps the block Markdown of its value. Integration tests of the render: no title page, and
the cut of a long value and of a long cell.
