---
id: "003113"
title: A choice of three or more cases is a switch
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
implementation:
  - frontend/src/app
scope:
  - frontend/src/app
  - frontend/vendor/ui-kit
---

# A choice of three or more cases is a switch

A template that chooses one of three or more cases must use `@switch` with one `@case` for each
case. It must not use a chain of `@if` and `@else if` for this. When the cases come from more
than one signal, for example loading, not found, error and loaded, the component must compute
one value that names the case, and the template must switch on that value.

Reason: One value names each case once, so a case cannot hide behind the order of the
conditions, and a new case is one `@case`.

Test: A review of each template change.
