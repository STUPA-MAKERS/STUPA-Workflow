---
id: "002768"
title: The graph shows linked Paperless documents
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---

# The graph shows linked Paperless documents

The graph page must show each linked Paperless document as a node with the icon and the name of
its kind, and its links as edges, for a person with `paperless.use` while the part of 002767 is
on. The graph must have a filter for the kind. A person without the permission must see neither
the node nor its edges.

Reason: The graph shows every link. A link kind that is missing there would be an exception
that a person must know.

Test: A backend unit test reads the graph with and without `paperless.use`.
