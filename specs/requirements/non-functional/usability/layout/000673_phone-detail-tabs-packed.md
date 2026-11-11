---
id: "000673"
title: The tabs of a phone detail are packed at the start
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - frontend/src/app/pages/tickets
  - frontend/vendor/ui-kit/src/lib/tabs
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The tabs of a phone detail are packed at the start

On the phone the tabs of a detail view must stand packed at the start of the tab line, each
as wide as its text. They must not be spread over the full width. This applies also to the
ticket detail.

Reason: Antrag and Gremium use packed tabs, and the Gremium has five tabs that do not fit
when they are spread. The ticket spreads two tabs over the full width.

Test: A unit test of the ticket detail at phone width expects the packed tab variant.
