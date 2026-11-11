---
id: "000496"
title: Every page links to the accessibility statement
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/src/app/features/help/a11y-menu/a11y-menu.component.spec.ts:A11yMenuComponent"
  - "frontend/src/app/layout/site-footer/site-footer.component.spec.ts:SiteFooterComponent"
implementation:
  - frontend/src/app/features/help/a11y-menu/a11y-menu.component.html
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Every page links to the accessibility statement

The accessibility menu (000647) must link to `/accessibility` on every page, with and without a
login. The footer and the help menu must not link to it, because one link in one known place is
enough and a second one in the footer is easy to miss on pages without a footer (000199).

Reason: The law requires that a user can find the statement from every page.
