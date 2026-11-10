---
id: "000631"
title: A settings row is a row of a row group, 56 px high
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/settings-row.styles.spec.ts:SettingsRows"
implementation:
  - frontend/vendor/ui-kit/src/styles/rowgroup.scss
  - frontend/src/app/settings-row.styles.spec.ts
  - frontend/src/app/pages/admin/notifications/notification-settings.component.html
  - frontend/src/app/pages/admin/help-tickets/help-tickets.component.html
  - frontend/src/app/pages/account/notifications.component.html
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A settings row is a row of a row group, 56 px high

A row that holds one setting (a label and a switch, or a label, a choice and a switch) must be
a child of the shared row group (`.rowgroup`). The row must be at least 56 px high. Its
content must start 16 px from the left edge and end 16 px before the right edge. A page must
not set the surface, the gap or the corners of such a row in its own stylesheet.

This applies to the pages Benachrichtigungen and Hilfe & Tickets of Verwaltung and to
Konto > Benachrichtigungen.

Reason: One shared row gives the three pages the same height, inset, surface and corners. A
row that a page draws by itself drifts from the other row groups with the next change.

Test: A source test of the three templates expects the classes `rowgroup rowgroup--settings`
on the list of the rows and no `min-height`, `background` or `border-radius` for the row in
the stylesheet of the page. A screenshot shows the three pages.
