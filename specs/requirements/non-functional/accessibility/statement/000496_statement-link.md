---
id: "000496"
title: Every page links to the accessibility statement
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/features/help/help-menu/help-menu.component.spec.ts:HelpMenuComponent"
  - "frontend/src/app/layout/site-footer/site-footer.component.spec.ts:SiteFooterComponent"
implementation:
  - frontend/src/app/features/help/help-menu/help-menu.component.html
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Every page links to the accessibility statement

The statement route of the framework config (ui-kit:002287) must be `/accessibility`.

Reason: The law requires that a user can find the statement from every page.
