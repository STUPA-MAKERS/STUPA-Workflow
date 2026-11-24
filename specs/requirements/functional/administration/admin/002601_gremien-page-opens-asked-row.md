---
id: "002601"
title: The Gremien page opens and shows the Gremium of the link
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/src/app/pages/admin/committees/gremien.component.spec.ts:AdminGremienComponent"
implementation:
  - frontend/src/app/pages/admin/committees/gremien.component.ts
scope:
  - frontend/src/app/pages/admin/committees
---

# The Gremien page opens and shows the Gremium of the link

When the Gremien page of the Verwaltung loads with the query parameter `open=<gremium id>` and
the list holds that Gremium, the page must open the row of that Gremium instead of the first
row, and must scroll the row into view. When the list does not hold that Gremium, the page must
open the first row, as without the parameter.

Reason: A link to one Gremium from an other page must show that Gremium, not the first Gremium
of the list.

Test: A frontend test that `open=<id>` opens that row only and scrolls it into view, and that an
unknown id opens the first row.
