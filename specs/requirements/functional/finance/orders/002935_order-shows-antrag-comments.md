---
id: "002935"
title: The detail of a Bestellung shows the comments of its Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/pages/orders/order-comments.directive.ts
scope:
  - frontend/src/app/pages/applications
  - backend/app/modules/applications
---

# The detail of a Bestellung shows the comments of its Antrag

A Bestellung must not have comments of its own. The detail of a Bestellung must show the
comments of its Antrag and the field for a new comment. A comment that a person writes there
must be a comment of the Antrag. The read, the write and the visibility of these comments must
follow the rules of the comments of the Antrag.

Reason: The people talk about a purchase where they talk about the Antrag. A second place for
comments would split one conversation in two.

Test: A frontend unit test opens the detail of a Bestellung, reads the comments of the Antrag
and sends a comment to the comment route of the Antrag.
