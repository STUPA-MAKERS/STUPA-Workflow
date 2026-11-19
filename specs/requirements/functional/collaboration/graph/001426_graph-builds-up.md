---
id: "001426"
title: The graph builds up piece by piece
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - frontend/src/app/pages
---
# The graph builds up piece by piece

The page must load the graph in pages of at most 60 nodes, the newest nodes first. The page
must add each page to the drawing when it arrives, and each new node must appear with a short
scale-in next to a neighbour that already shows. The page must load the next page by itself
until 300 nodes show. Then the action "Mehr laden" (`Load more`) must load the next 300. The
nodes that already show must keep their place when new nodes arrive, apart from the settling of
the layout. A change of a filter must start the build-up again.

Reason: The first nodes show at once, and the person watches the structure grow instead of
waiting for one large answer. The stop at 300 keeps the drawing readable and the browser fast.

Test: A frontend unit test feeds two pages and checks that the nodes of the first page keep
their identity and that the page stops at 300 nodes.
