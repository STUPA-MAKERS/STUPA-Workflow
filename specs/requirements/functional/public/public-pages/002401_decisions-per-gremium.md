---
id: "002401"
title: The public decisions have one page per Gremium
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-21
implementation:
  - frontend/src/app/features/public-protocols
scope:
  - frontend/src/app/features/public-protocols
  - frontend/src/app/app.routes.ts
---

# The public decisions have one page per Gremium

The page `/decisions` must list the same Gremien as `/protocols` (002400). A row must open
the page `/decisions/<slug>` of its Gremium. The page of a Gremium must list the public
decisions (F/public/public-pages/000926) of that Gremium only, with the search and the
Semester filter. It must not have a Gremium filter.

Reason: The decisions belong to the Gremium that made them, as its protocols do.

Test: A frontend unit test opens `/decisions/<slug>` and finds that the list reads only the
decisions of that Gremium.
