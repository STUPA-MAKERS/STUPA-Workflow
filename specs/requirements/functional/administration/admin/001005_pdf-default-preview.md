---
id: "001005"
title: The branding page shows the built-in PDF graphics
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "frontend/src/app/pages/admin/branding/branding-editor.component.spec.ts:BrandingEditorComponent"
implementation:
  - frontend/src/assets/logos/pdf-stupa.svg
  - frontend/src/assets/logos/pdf-skyline.svg
  - frontend/src/app/pages/admin/branding/branding-editor.component.html
  - frontend/src/app/pages/admin/branding/branding-editor.component.ts
  - frontend/src/app/pages/admin/branding/branding-editor.component.scss
scope:
  - frontend/src/app/pages/admin/branding
  - frontend/src/assets/logos
---

# The branding page shows the built-in PDF graphics

While the export logo (000891) or the footer graphic (000892) is the built-in default, its row
on the branding page (`/admin/branding`) must show that graphic as its image: the STUPA logo
or the Skyline, as the logo rows above it show their built-in logos. The image must sit on a
white surface in every theme, because the PDF page is white. An upload keeps the file icon and
no preview (000891). An empty slot keeps the image icon.

The frontend serves a copy of the two built-in graphics of the render service
(`hsrtreport-typst`: `logos/STUPA.svg`, `Skyline.svg`) from `assets/logos/`. A change of a
built-in graphic in the render service must change the copy in the same pull request.

Reason: The admin sees what the PDFs carry without exporting a PDF first. The word "Standard"
alone does not say which graphic that is.

Test: A test of the branding page shows the built-in image in both rows while they are the
default, and no image after an upload or a remove, and the default again after a reset.
