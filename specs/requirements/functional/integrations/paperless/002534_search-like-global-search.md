---
id: "002534"
title: The Paperless search looks like the global search
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - frontend/src/app/
---

# The Paperless search looks like the global search

The Paperless search must be a search window with the look of the `Verknüpfen` picker
(ui-kit:001977): the same panel, the same search field with the key `Esc` as the close button,
and the same floating panel on a phone. The window must show the hits as rows with the title,
the document type and the date of the document. The arrow keys must move the selection, and
Enter must pick the selected hit.

Reason: The search of Paperless is the same gesture as the global search and the `Verknüpfen`
search. A third look for the same thing makes the person look twice.

Test: A frontend unit test opens the search, closes it with the key `Esc`, and picks a hit
with Enter.
