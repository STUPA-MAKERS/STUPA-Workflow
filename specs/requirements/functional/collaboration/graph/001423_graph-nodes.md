---
id: "001423"
title: The graph shows the elements that have a relation
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules
  - frontend/src/app/pages
---
# The graph shows the elements that have a relation

The graph must show the kinds of F/collaboration/links/001400: Antrag, meeting, TOP, vote,
Termin, Gremium, invoice, Buchung, cost centre, ticket and card. An element must show only
when it has at least one relation of F/collaboration/graph/001424 to another element that
shows. The switch "Auch ohne Verknüpfung" (`Also without a link`) must add the readable
elements without a relation. The switch must be off at first.

Reason: The page is about relations. Several hundred single points without a line hide the
structure that the person looks for.

Test: A backend unit test reads the graph of a person with one linked and one single Antrag,
with the switch off and on.
