---
id: "001982"
title: The Anträge list has the FABs Antrag stellen and Antrag erfassen
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/pages/applications/applications-list.component.spec.ts:ApplicationsListComponent"
implementation:
  - frontend/src/app/pages/applications/applications-list.component.html
  - frontend/vendor/ui-kit/src/lib/fab/fab-group.component.ts
scope:
  - frontend/src/app/pages/applications
  - frontend/vendor/ui-kit/src/lib/fab
---

# The Anträge list has the FABs Antrag stellen and Antrag erfassen

The Anträge list must show the FAB "Antrag stellen" to every user, on every width. The FAB must
open `/apply` and must show the icon `form`. A holder of `application.create_on_behalf` must
also see the FAB "Antrag erfassen" (000122), with the icon `fileplus`. The two FABs must stand
side by side in one group at the bottom end of the list, with "Antrag erfassen" at the end. When
both show, "Antrag erfassen" must have the accent surface and "Antrag stellen" the neutral surface.
When "Antrag stellen" shows alone, it must have the accent surface. While the capture form is open,
the page must show neither FAB.

Reason: A Gremium member also files Anträge in their own name, and the Anträge list is where
they look for that action.

Test: `applications-list.component.spec.ts`, describe `Antrag stellen`.
