---
id: "001408"
title: Verknüpfen searches every kind
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/features/todos
scope:
  - frontend/src/app/features/todos
---

# Verknüpfen searches every kind

The action `Verknüpfen` (`Link`) must open one search over every kind of
F/collaboration/links/001400, with a filter by kind. The search must show only elements that
the person reads and must not show an element that is already linked or the element itself.
Without a search term the search must show the newest cards of the person, as 000548 says for
cards.

Reason: One picker for every detail. A person learns it once.

Test: A frontend unit test opens the search from an invoice and checks that the invoice and its
linked Antrag are not offered.
