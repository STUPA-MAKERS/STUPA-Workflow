---
id: "000520"
title: Each page has landmarks and one h1
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/vendor/ui-kit/shell/src/shell/shell.component.spec.ts:ShellComponent"
  - "frontend/src/app/layout/shell.component.spec.ts:ShellComponent"
implementation:
  - frontend/vendor/ui-kit/shell/src/shell/shell.component.html
  - frontend/src/app/layout/public-header/public-header.component.html
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Each page has landmarks and one h1

Each page must have the landmarks `header`, `nav` and `main`, and exactly one `h1`. Headings
must not skip a level.

Reason: WCAG 1.3.1 and 2.4.6. A screen reader user moves through a page by landmarks and
headings.
