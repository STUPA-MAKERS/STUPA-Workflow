---
id: "001420"
title: The page Graph shows the elements of a person and their relations
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules
  - frontend/src/app/pages
---
# The page Graph shows the elements of a person and their relations

The page "Graph" at `/graph` must show the elements that the signed-in person reads as nodes and
the relations between them as lines. The navigation must have its own entry for the page, in
the rail and in the menu "Mehr" of the phone. The page must not store data of its own. It must
read the elements and the links that the modules already keep.

Reason: A person sees in one picture how Anträge, meetings, Buchungen and cards belong
together. A list shows one element and its links only.

Test: A frontend unit test of the navigation finds the entry, and a backend unit test reads
the graph of a person with two linked elements.
