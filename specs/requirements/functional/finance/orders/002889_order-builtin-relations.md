---
id: "002889"
title: The relations of a Bestellung show without a link
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/todos
  - backend/app/modules/graph
---

# The relations of a Bestellung show without a link

The Antrag, the invoice and the bookings of a Bestellung must show in its "Verknüpft" list and
in the graph as built-in relations (F/collaboration/graph/001424). The platform must not store a
link row for them. A person must not be able to remove them in "Verknüpft".

Reason: These relations are fields of the Bestellung. A second link row for the same pair would
show the relation two times and could stay after the field changed.

Test: A backend unit test of the graph build reads the three relations of a Bestellung. A
frontend test shows them without the remove button.
