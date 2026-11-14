---
id: "000892"
title: Every PDF carries the footer graphic of the branding
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/unit/modules/files/test_pdf_branding.py:test_the_render_config"
  - "backend/tests/integration/modules/admin/test_pdf_branding_db.py:test_the_footer_graphic_has_its_own_slot"
  - "backend/tests/unit/modules/protocol/test_protocol_images.py:test_render_sends_the_footer_graphic"
  - "typst/tests/test_document.py:test_the_footer_graphic_is_the_skyline_an_asset_or_none"
  - "frontend/src/app/pages/admin/branding/branding-editor.component.spec.ts:BrandingEditorComponent"
implementation:
  - backend/app/modules/site_config/models.py
  - backend/migrations/versions/6d89f29dead1_pdf_asset.py
  - backend/app/modules/admin/service/pdf_branding.py
  - backend/app/modules/admin/router.py
  - backend/app/modules/files/pdf_branding.py
  - backend/app/modules/protocol/service.py
  - backend/app/modules/documents/service.py
  - typst/typst_service/document.py
  - typst/template/protocol.typ
  - frontend/src/app/pages/admin/branding/branding-editor.component.ts
scope:
  - backend/app/modules/files/pdf_branding.py
  - backend/app/modules/admin
  - backend/app/modules/protocol/service.py
  - typst/template/protocol.typ
  - frontend/src/app/pages/admin/branding
---

# Every PDF carries the footer graphic of the branding

The branding page (`/admin/branding`) must offer the footer graphic: the graphic at the foot
of each page of a PDF. Every PDF with a footer graphic must take it from the branding: the
meeting protocol (also its public version), the Antrag PDF (000881), and the Antrag as an
Anlage of a protocol (000884). The template must not build a graphic in.

The footer graphic is the Skyline by default: the migration sets it. The admin can replace it
with an upload, set the default again, or remove it. Without a footer graphic, the pages have
none. The upload follows the rules of the export logo (000891): PNG, JPEG, WebP, SVG or PDF by
its bytes, at most 2 MB, the virus scan, saved at once, no preview, and a download only as an
attachment.

Reason: The Skyline shows one campus. A graphic that the template builds in cannot be changed
when the design of the student body changes.

Test: Tests set the default, upload and remove the footer graphic and render the protocol with
an upload and without a graphic. A test of the render service maps the key to the Skyline, an
asset or no graphic. A test of the branding page removes the footer graphic.
