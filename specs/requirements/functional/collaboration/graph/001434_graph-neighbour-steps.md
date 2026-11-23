---
id: "001434"
title: The graph shows the neighbours of the hits up to a count of steps
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/graph/test_graph_build.py:test_the_neighbours_of_a_hit_show_up_to_the_steps"
  - "backend/tests/unit/modules/graph/test_graph_build.py:test_a_hit_of_the_search_shows_without_a_line"
  - "frontend/src/app/pages/graph/graph.component.spec.ts:GraphComponent"
implementation:
  - backend/app/modules/graph/build.py
  - frontend/src/app/pages/graph/graph.util.ts
  - frontend/src/app/pages/graph/graph.component.html
  - frontend/src/app/pages/graph/graph.component.scss
scope:
  - backend/app/modules
  - frontend/src/app/pages
---
# The graph shows the neighbours of the hits up to a count of steps

A hit is a node that passes the filters "Art" and "Zeitraum" and the search
(ui-kit:F/collaboration/graph/001425). The page must have a number field "Schritte" (`Steps`) with a
count from 0 to 5. The graph must show each hit, and each node that is at most this count of
lines away from a hit. Such a neighbour must show also when it does not pass the kind, the
period or the search. With 0 only the hits show.

A line counts as a step only when the filter "Beziehungen" shows it. A neighbour must still pass
the read rules (F/collaboration/graph/001422) and the features (F/collaboration/graph/001432):
an element that the person does not read shows only with "Ohne Zugriff zeigen", and then with
its kind only. "Auch ohne Verknüpfung" adds only hits without a line.

A hit of the search must show also when it has no line to another node that shows: with a term
in the search, each hit that the person reads shows at every count of steps, also at 0 and
also without "Auch ohne Verknüpfung". Without a term a node without a line shows only with
"Auch ohne Verknüpfung" (F/collaboration/graph/001423).

A fresh page must have 2 steps. The count must be in the query of the URL as `depth`; a query
without it means 2. The route `GET /api/graph` must take `depth`, and the server must apply
it. "Zurücksetzen" must set 2 again.

The field must not be in the bar of the filters. It must be a surface of its own over the
drawing, at the bottom start corner, opposite the zoom buttons at the bottom end corner, also on
a phone. Its name "Schritte" must be above the stepper: the minus button, the number and the
plus button in one line. The field must show also while the page loads and when the graph is
empty, so that the person can raise the count. The state of the build-up ("Wird aufgebaut",
"Mehr laden") must be at the end side of the field. The person must be able to change the
count with the keyboard (arrow up and down) and with the minus and the plus button.

Reason: A hit alone does not answer the question of the person. The person searches an Antrag
and wants to see its meeting, its vote and its Buchung, which the period or the search would
hide. The count sets how far the view reaches: a small count for one element, a large count
for a whole matter. A search that finds one element and shows an empty page at 0 steps looks
like a search without a hit, and the count then seems to be wrong by one. The count is a
setting of the view, as the zoom is, so it is in a corner of the drawing opposite the zoom,
and the bar of the filters keeps its room for the search and the filters.

Test: A backend unit test with a chain of nodes and the counts 0, 1 and 2; a backend unit test
with a hit of the search that has no line to another hit, at 0 steps; a frontend unit test that
reads the count from the URL and writes it back.
