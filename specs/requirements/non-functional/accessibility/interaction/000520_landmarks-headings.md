---
id: "000520"
title: Each page has landmarks and one h1
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Each page has landmarks and one h1

Each page must have the landmarks `header`, `nav` and `main`, and exactly one `h1`. Headings
must not skip a level.

Reason: WCAG 1.3.1 and 2.4.6. A screen reader user moves through a page by landmarks and
headings.
