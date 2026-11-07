---
id: "000532"
title: A sheet over a sheet is as opaque as the first one
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-07
implementation:
  - frontend/vendor/ui-kit
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A sheet over a sheet is as opaque as the first one

A dialog, a side sheet and a bottom sheet must have the same tint and the same blur at every
level. A sheet that opens from a dialog or from another sheet, such as the phone picker of a
select in a dialog, must look the same as a sheet that opens from the page. The glass colour of
a dialog or a sheet must come from a token that the content of a glass surface does not change.

Reason: The content of a glass surface turns the surface tokens into light overlays, so the
fields on the glass show the glass through them. A sheet that opens inside that content
inherits the overlays. Its own glass then has a tint of about 5 % instead of 85 %, and the page
behind it reads through its rows.

Test: `frontend/vendor/ui-kit/src/lib/side-sheet/side-sheet.component.spec.ts` (a sheet inside
a dialog body has the same background as a sheet on the page) and a check of the screenshots.
