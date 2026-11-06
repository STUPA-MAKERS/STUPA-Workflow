---
id: "000511"
title: Each page has its own title
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - frontend/src/app/core/branding
---

# Each page has its own title

The document title must be `<page title> – <app name>`. The page title must come from the
`title` of the route, and from the name of the item on a detail page.

Reason: WCAG 2.4.2. A screen reader reads the title first, and the tab list shows it.
