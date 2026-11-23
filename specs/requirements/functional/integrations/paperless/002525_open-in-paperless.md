---
id: "002525"
title: An element with a filed document links to Paperless
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - frontend/src/app/
  - backend/app/
---

# An element with a filed document links to Paperless

The detail page of a protocol, an Antrag and a Haushaltsplan must show the entry `In Paperless
öffnen` when the element has a filed document. The entry must open the document in Paperless
in a new tab. Only a person with `paperless.use` must see it.

Reason: The filed document and its element must point to each other (002519).

Test: A unit test of the detail page expects the entry with the permission and no entry
without it.
