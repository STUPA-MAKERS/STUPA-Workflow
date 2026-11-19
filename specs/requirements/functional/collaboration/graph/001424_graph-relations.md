---
id: "001424"
title: The graph shows links and the built-in relations
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules
  - frontend/src/app/pages
---
# The graph shows links and the built-in relations

The graph must show each link of F/collaboration/links/001400 as a solid line. It must also
show these built-in relations as dashed lines:

| Relation | Source |
| --- | --- |
| Antrag and its Vorgänger | `application_link` |
| Antrag and its TOP | the Antrag of an agenda item |
| Antrag and its vote | the Antrag of a vote |
| Antrag and its cost centre | the cost centre of an Antrag |
| Antrag and its Buchung | the Antrag of a Buchung |
| meeting and its TOP | the meeting of an agenda item |
| meeting and its Gremium | the Gremium of a meeting |
| TOP and its vote | the agenda item of a vote |
| TOP and its card | the card of an agenda item |
| invoice and its Buchung | the invoice of a Buchung |
| Buchung and its cost centre | the cost centre of a Buchung |
| Termin and its Gremium | an invitation of a Gremium |

A vote with a TOP must not also have a line to the meeting of the TOP. The filter "Beziehungen"
(`Relations`) must have the choices "Alle" (`All`), "Nur Verknüpfungen" (`Links only`) and
"Nur feste Beziehungen" (`Built-in only`). Two elements with a link and a built-in relation must
show one solid line.

Reason: Most relations of the platform are not links that a person made by hand. A meeting has
its TOPs and a Buchung has its invoice. Without them the graph is nearly empty and hides how
the work really connects. The line style tells the two sorts apart without colour
(NF/accessibility/perception/000502).

Test: A backend unit test builds a meeting with a TOP of an Antrag and a vote, and reads the
lines with each choice of the filter.
