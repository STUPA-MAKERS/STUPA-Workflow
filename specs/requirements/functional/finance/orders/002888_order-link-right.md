---
id: "002888"
title: The change right of a Bestellung in a link is order.manage
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/todos
---

# The change right of a Bestellung in a link is order.manage

For the rule of F/collaboration/links/001404 the change right of a Bestellung must be
`order.manage`.

Reason: The link rule needs one change right per kind. The right to write a Bestellung is the
right to change how others see it.

Test: A backend unit test refuses a link between a Bestellung and a meeting for a person with
read rights only and accepts it with `order.manage`.
