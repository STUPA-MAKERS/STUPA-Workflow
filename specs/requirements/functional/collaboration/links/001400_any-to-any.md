---
id: "001400"
title: Any two elements can link to each other
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/todos/link_service.py
  - backend/app/modules/todos/models.py
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# Any two elements can link to each other

A link must connect two elements of these kinds in any combination: Antrag, meeting, TOP, vote,
Termin, Gremium, invoice, Buchung, cost centre, ticket and card. Two elements of the same kind
must be able to link too. An element must not link itself. Two elements must have at most one
link.

Reason: Work does not always start on a card. An invoice belongs to an Antrag, a TOP to a
ticket, a Termin to a meeting. Without a card in between, these relations get lost.

Test: A backend unit test links an invoice to an Antrag, a TOP to a ticket and two Anträge to
each other, and refuses a self link and a second link between the same two elements.
