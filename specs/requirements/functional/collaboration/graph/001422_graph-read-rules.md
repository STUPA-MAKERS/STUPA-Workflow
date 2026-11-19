---
id: "001422"
title: The graph shows only what the person reads
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules
---
# The graph shows only what the person reads

A node must show only when the person reads the element by the read rule of its kind, or
through a card that the person reads (F/collaboration/todos/000487). A relation must show only
when both of its ends show. The graph must not show a node "kein Zugriff" (`no access`), and it
must not show a count of hidden elements. An element that the person reads only through a card
must open in the read-only view of F/collaboration/links/001409.

Reason: A hidden node with a line would tell that a link to an unreadable element exists and
to what it connects. The graph must not be a way past the read rule of a kind.

Test: A backend unit test links an Antrag to an invoice and reads the graph as a person
without a budget read right: the answer has no invoice node and no line to it.
