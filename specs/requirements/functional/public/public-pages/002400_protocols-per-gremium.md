---
id: "002400"
title: The public protocols have one page per Gremium
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-21
implementation:
  - frontend/src/app/features/public-protocols
  - backend/app/modules/protocol/public.py
scope:
  - frontend/src/app/features/public-protocols
  - frontend/src/app/app.routes.ts
---

# The public protocols have one page per Gremium

The page `/protocols` must list the public Gremien that have at least one public protocol
(F/public/public-pages/000171), by name. A row must show the day of the newest public
protocol of its Gremium and must show no count. A row must open the page `/protocols/<slug>` of its
Gremium. The page of a Gremium must list the public protocols of that Gremium only, with the
search and the Semester filter. It must not have a Gremium filter. The page of one protocol
must stay at `/protocols/<id>`.

Reason: Each Gremium keeps its own protocols. A reader looks for the protocols of one
Gremium, so a page per Gremium is shorter than one list with a filter.

Test: A frontend unit test opens `/protocols` and finds one row per public Gremium, and opens
`/protocols/<slug>` and finds that the list reads only the protocols of that Gremium.
