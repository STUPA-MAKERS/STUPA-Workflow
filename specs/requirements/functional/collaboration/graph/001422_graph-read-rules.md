---
id: "001422"
title: The graph shows only what the person reads
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/graph/service.py
  - frontend/src/app/pages/graph
scope:
  - backend/app/modules
---
# The graph shows only what the person reads

A node must show its title, its date and its URL only when the person reads the element by the
read rule of its kind, or through a card that the person reads (F/collaboration/todos/000487).
An element that the person reads only through a card must open in the read-only view of
F/collaboration/links/001409. The switch "Ohne Zugriff zeigen" (`Show without access`) must
decide about the other elements. The switch must be off at first.

With the switch off, the graph must not show an element that the person does not read, no
relation to it and no count of hidden elements. With the switch on, an element that the person
does not read and that has a relation to a node the person reads must show as a grey node
"<Art> (kein Zugriff)" (`<Kind> (no access)`), without title, date, URL or detail. The grey
node must show only its relations to nodes that the person reads. A press on it must not open
anything. The filters "Zeitraum", "Gremium" and the search must not apply to a grey node.

Reason: The section `Verknüpft` already tells a reader that an unreadable element is linked
(F/collaboration/links/001405), so the grey node tells nothing new about one element. The
switch is off at first, because the drawing reads better without nodes that open nothing. A
relation between two unreadable elements stays hidden, because no detail page shows it to the
person.

Test: A backend unit test links an Antrag to an invoice and reads the graph as a person
without a budget read right. With the switch off the answer has no invoice node and no line to
it. With the switch on the node has the kind only.
