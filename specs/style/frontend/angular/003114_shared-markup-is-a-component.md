---
id: "003114"
title: Markup that two templates repeat is one component
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

# Markup that two templates repeat is one component

A block of markup that occurs in two or more templates must be one component that each of
these templates uses. The component lives where 000079 puts it. A block that occurs twice in
one template must be one `ng-template`.

Reason: A copied block drifts from its original, and a change to one copy misses the others.

Test: A review of each template change.
