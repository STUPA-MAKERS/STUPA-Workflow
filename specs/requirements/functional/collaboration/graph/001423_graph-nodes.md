---
id: "001423"
title: The graph shows the elements that have a relation
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - backend/app/modules/graph/build.py
  - frontend/src/app/pages/graph
scope:
  - backend/app/modules
  - frontend/src/app/pages
---
# The graph shows the elements that have a relation

The graph must show the kinds of F/collaboration/links/001400: Antrag, meeting, TOP, vote,
Termin, Gremium, invoice, Buchung, cost centre, ticket and card. An element must show only
when it has at least one relation of F/collaboration/graph/001424 to another element that
shows. The switch "Auch ohne Verknüpfung" (`Also without a link`) must add the readable
elements without a relation. The switch must be off at first. A hit of the search is the
exception: it shows also without a relation (F/collaboration/graph/001434).

Reason: The page is about relations. Several hundred single points without a line hide the
structure that the person looks for. A search names what the person looks for, so its hits
are few and must not hide.

Test: A backend unit test reads the graph of a person with one linked and one single Antrag,
with the switch off and on.
