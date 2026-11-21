---
id: "002404"
title: An old Gremium filter link opens the page of the Gremium
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-21
implementation:
  - frontend/src/app/features/public-protocols
scope:
  - frontend/src/app/features/public-protocols
---

# An old Gremium filter link opens the page of the Gremium

A link `/protocols?committee=<id>` or `/decisions?committee=<id>` with one public Gremium
must open the page of that Gremium and replace the address. A link with more than one
Gremium, or with no public Gremium, must open the list of Gremien.

Reason: Mails, bookmarks and other pages hold links with the old Gremium filter.

Test: A frontend unit test opens `/protocols?committee=<id>` and finds the address
`/protocols/<slug>`.
