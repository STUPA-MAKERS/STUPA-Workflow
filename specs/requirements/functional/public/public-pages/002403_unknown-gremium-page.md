---
id: "002403"
title: An unknown Gremium page shows that it has no protocols
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-21
implementation:
  - frontend/src/app/features/public-protocols
scope:
  - frontend/src/app/features/public-protocols
---

# An unknown Gremium page shows that it has no protocols

When the slug of `/protocols/<slug>` or `/decisions/<slug>` names no public Gremium with a
public protocol, the page must show the empty state with a link to the list of Gremien. The
page must not tell if a Gremium with that slug exists.

Reason: A Gremium that does not publish its protocols is not public, so the page must not
show it.

Test: A frontend unit test opens `/protocols/unknown` and finds the empty state and the link
to `/protocols`.
