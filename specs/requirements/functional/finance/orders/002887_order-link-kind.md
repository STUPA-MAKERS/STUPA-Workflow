---
id: "002887"
title: A Bestellung is a link kind
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/todos
  - backend/app/modules/orders
---

# A Bestellung is a link kind

A link (F/collaboration/links/001400) must be able to have a Bestellung as an end. The kind must
be `order` with the name "Bestellung" and must stand after the Buchung in the order of the
kinds. Its read rule must be 002863, and a card must give the read of a linked Bestellung like
the read of a linked Antrag. Its change right for F/collaboration/links/001404 must be
`order.manage`. The delete of a Bestellung must delete its links
(F/collaboration/links/001402).

Reason: A Bestellung belongs to a card, a TOP or a document of the archive too. As a link end it
shows in "Verknüpft" and takes these relations without new fields.

Test: A backend unit test links a Bestellung to a card with `order.manage`, refuses the link
with read rights only and deletes the Bestellung with its links.
