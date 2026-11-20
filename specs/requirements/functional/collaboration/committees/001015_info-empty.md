---
id: "001015"
title: An empty Info tab shows only to its editors
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - frontend/src/app/features/gremien/gremien.util.ts
  - frontend/src/app/features/gremien/gremium-info
scope:
  - frontend/src/app/features/gremien
---

# An empty Info tab shows only to its editors

When a Gremium has no text and no link, the Info tab must show only to a holder of
`info.write`. The editor must then see the empty state of the app (ui-kit:000205) with the action
"Info bearbeiten". A reader must not see an empty Info tab, and the first other tab must open.

Reason: An empty tab tells a reader nothing and costs a tap.

Test: A component test with and without `info.write`.
