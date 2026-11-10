---
id: "000496"
title: Every page links to the accessibility statement
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/src/app/layout/site-footer/site-footer.component.spec.ts:SiteFooterComponent"
  - "frontend/src/app/features/help/help-menu/help-menu.component.spec.ts:HelpMenuComponent"
implementation:
  - frontend/src/app/layout/site-footer/site-footer.component.html
  - frontend/src/app/features/help/help-menu/help-menu.component.html
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Every page links to the accessibility statement

The footer and the help menu must link to `/accessibility` on every page. The link must
be there with and without a login.

Reason: The law requires that a user can find the statement from every page.
