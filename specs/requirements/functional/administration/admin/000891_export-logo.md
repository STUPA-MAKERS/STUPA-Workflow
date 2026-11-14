---
id: "000891"
title: Exported PDFs carry the export logo of the branding
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/unit/modules/files/test_pdf_branding.py:test_the_upload_policy"
  - "backend/tests/unit/modules/files/test_pdf_branding.py:test_the_render_config"
  - "backend/tests/unit/modules/admin/test_pdf_branding_router.py:test_the_pdf_branding_routes"
  - "backend/tests/integration/modules/admin/test_pdf_branding_db.py:test_the_export_logo_is_uploaded_replaced_reset_and_removed"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_the_pdf_carries_the_export_logo"
  - "backend/tests/unit/modules/documents/test_application_markdown.py:test_the_pdf_carries_the_export_logo"
  - "frontend/src/app/pages/admin/branding/branding-editor.component.spec.ts:BrandingEditorComponent"
implementation:
  - backend/app/modules/site_config/models.py
  - backend/migrations/versions/6d89f29dead1_pdf_asset.py
  - backend/app/modules/admin/service/pdf_branding.py
  - backend/app/modules/admin/router.py
  - backend/app/modules/files/pdf_branding.py
  - backend/app/modules/budget/plan_router.py
  - backend/app/modules/protocol/plan_anlage.py
  - backend/app/modules/documents/service.py
  - frontend/src/app/pages/admin/branding/branding-editor.component.ts
scope:
  - backend/app/modules/site_config
  - backend/app/modules/admin
  - backend/app/modules/files/pdf_branding.py
  - backend/app/modules/budget
  - backend/app/modules/documents
  - backend/app/modules/protocol/plan_anlage.py
  - frontend/src/app/pages/admin/branding
---

# Exported PDFs carry the export logo of the branding

The branding page (`/admin/branding`) must offer one more logo: the export logo. Each PDF
that the platform exports must carry the export logo, and no other logo. This covers the
Antrag PDF (000881), the PDF of a Haushaltsplan (000875), and both as an Anlage of a
protocol (000884, 000876). The meeting protocol itself must keep the logos of the design of
its Gremium.

An export must not take a logo from the design of a Gremium. The export logo is the STUPA
logo by default: the migration sets it. The admin can replace it with an upload, set the
default again, or remove it. Without an export logo, the PDF has no logo, and the render
service must not add one of its own. The logo keeps its place:
at the top of the first page of a Haushaltsplan, and in the footer of each page of an Antrag.

The export logo must be PNG, JPEG, WebP, SVG or PDF by its bytes, at most 2 MB, and pass the
virus scan. It saves at once, apart from the other branding fields. Its bytes go to the render
service only: the page shows no preview of it, the public site config does not carry it, and a
download of it is always an attachment, because an SVG in the app origin can run script.

Reason: The platform has one sender. A Gremium design names the Gremium of a protocol, but an
export comes from the platform, and a logo that the template builds in cannot be changed.

Test: Tests upload an SVG and a PDF, refuse an ICO, replace, reset and remove the export logo, and render the Antrag and the plan with
and without it: with it, the render gets the logo as its only logo; without it, an empty
logo list. A test of the branding page shows the default, picks, resets and removes the export logo.
