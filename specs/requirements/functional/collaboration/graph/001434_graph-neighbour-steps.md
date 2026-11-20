---
id: "001434"
title: The graph shows the neighbours of the hits up to a count of steps
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "backend/tests/unit/modules/graph/test_graph_build.py:test_the_neighbours_of_a_hit_show_up_to_the_steps"
  - "frontend/src/app/pages/graph/graph.component.spec.ts:GraphComponent"
implementation:
  - backend/app/modules/graph/build.py
  - frontend/src/app/pages/graph/graph.util.ts
  - frontend/src/app/pages/graph/graph.component.html
scope:
  - backend/app/modules
  - frontend/src/app/pages
---
# The graph shows the neighbours of the hits up to a count of steps

A hit is a node that passes the filters "Art" and "Zeitraum" and the search
(F/collaboration/graph/001425). The page must have a number field "Schritte" (`Steps`) with a
count from 0 to 5. The graph must show each hit, and each node that is at most this count of
lines away from a hit. Such a neighbour must show also when it does not pass the kind, the
period or the search. With 0 only the hits show.

A line counts as a step only when the filter "Beziehungen" shows it. A neighbour must still pass
the read rules (F/collaboration/graph/001422) and the features (F/collaboration/graph/001432):
an element that the person does not read shows only with "Ohne Zugriff zeigen", and then with
its kind only. "Auch ohne Verknüpfung" adds only hits without a line.

A fresh page must have 2 steps. The count must be in the query of the URL as `depth`; a query
without it means 2. The route `GET /api/graph` must take `depth`, and the server must apply
it. "Zurücksetzen" must set 2 again.

The field must be at the end side of the search and must stay there: it must not scroll with
the filters. On a phone it must be in the line of the search. The person must be able to
change the count with the keyboard (arrow up and down) and with a minus and a plus button.

Reason: A hit alone does not answer the question of the person. The person searches an Antrag
and wants to see its meeting, its vote and its Buchung, which the period or the search would
hide. The count sets how far the view reaches: a small count for one element, a large count
for a whole matter.

Test: A backend unit test with a chain of nodes and the counts 0, 1 and 2; a frontend unit
test that reads the count from the URL and writes it back.
