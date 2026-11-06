---
id: "000074"
title: Run the production build after style changes
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/
scope:
  - frontend/
---

# Run the production build after style changes

Run `npm run build` after a change to component styles or to a template with nullable signals
or i18n parameters. A component style must stay below 28 kB. The initial bundle must stay
below 1.1 MB.

Reason: jest and tsc pass where the AOT build and the budgets fail.
