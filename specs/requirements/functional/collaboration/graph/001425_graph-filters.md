---
id: "001425"
title: The graph has filters above the drawing
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - backend/app/modules/graph/build.py
  - frontend/src/app/pages/graph/graph.util.ts
scope:
  - backend/app/modules
  - frontend/src/app/pages
---
# The graph has filters above the drawing

The page must have these filters:

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

A fresh page must show the last 30 days: the period starts 30 days before today and has no
end. A fresh page must show every kind but the cost centres. A fresh page must show only the
links that a person made ("Nur Verknüpfungen"), not the relations of the data. The person can
choose every day, every kind and every relation; the query then holds `period=all`, `kinds=all`
and `rel=all`. A query without a period, without kinds or without relations means the fresh
page. "Zurücksetzen" (`Reset`) must go back to the fresh page, and
it must show only while a filter differs from the fresh page.

The drawing must fill the height of the page. The filters and the panel of the chosen node
must float over the drawing, the filters on one surface. The search and the filters must stay
in one line: when the room is short, the search gets narrower first, and then the filters
scroll sideways. They must not wrap to a second line. The page must not show a title. On a
phone the drawing must fill the screen above the bar of the shell, and the filters must be one
strip from edge to edge at the top of the drawing, with the search in its full width.

Reason: A graph of every year is too large to read. The person narrows it to the question at
hand, and the URL keeps the view for a reload or for a colleague. The work of the last weeks is
the usual question, and the cost centres connect to almost every element, so they tie the
whole drawing into one knot. The relations of the data are many and say what the detail pages
say already; the links are what a person decided to connect.

Test: A backend unit test per filter, and a frontend unit test that reads the filters from the
URL.
