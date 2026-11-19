---
id: "001425"
title: The graph has filters above the drawing
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules
  - frontend/src/app/pages
---
# The graph has filters above the drawing

The head of the page must have these filters:

| Filter | Effect |
| --- | --- |
| "Art" (`Kind`) | several kinds; only nodes of these kinds show |
| "Zeitraum" (`Period`) | from and to; only nodes with their date in the period show |
| "Gremium" | only nodes that belong to the Gremium show |
| "Beziehungen" (`Relations`) | the choices of F/collaboration/graph/001424 |
| search | only nodes with the term in their title show, and their neighbours |

The date of a node must be: the date of a meeting and of its TOPs, the start of a Termin, the
invoice date of an invoice, the invoice date of a Buchung and else its creation, the due date of
a card and else its creation, and the creation of an Antrag, a vote and a ticket. A Gremium and
a cost centre have no date and must pass every period. The filters must be in the query of the
URL. The server must apply the filters.

Reason: A graph of every year is too large to read. The person narrows it to the question at
hand, and the URL keeps the view for a reload or for a colleague.

Test: A backend unit test per filter, and a frontend unit test that reads the filters from the
URL.
