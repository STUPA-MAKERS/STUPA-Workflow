---
id: "000891"
title: Exported PDFs carry the export logo of the branding
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/unit/modules/site_config/test_export_logo.py:test_the_export_logo_slot"
  - "backend/tests/unit/modules/site_config/test_export_logo.py:test_the_export_logo_config"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_the_pdf_carries_the_export_logo"
  - "backend/tests/unit/modules/documents/test_application_markdown.py:test_the_pdf_carries_the_export_logo"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_export_logo_comes_from_the_active_branding"
  - "frontend/src/app/pages/admin/branding/branding-editor.component.spec.ts:BrandingEditorComponent"
implementation:
  - backend/app/modules/site_config/branding.py
  - backend/app/modules/site_config/export_logo.py
  - backend/app/modules/budget/plan_router.py
  - backend/app/modules/protocol/plan_anlage.py
  - backend/app/modules/documents/service.py
  - frontend/src/app/pages/admin/branding/branding-editor.component.ts
scope:
  - backend/app/modules/site_config
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

An export must not take a logo from the design of a Gremium, and the render service must not
add a built-in logo. Without an export logo, the PDF has no logo. The logo keeps its place:
at the top of the first page of a Haushaltsplan, and in the footer of each page of an Antrag.

The export logo is checked like the other branding logos (000372). The public site config
must not carry it, because only the server reads it.

Reason: The platform has one sender. A Gremium design names the Gremium of a protocol, but an
export comes from the platform, and a logo that the template builds in cannot be changed.

Test: Unit tests save and remove the export logo, and render the Antrag and the plan with
and without it: with it, the render gets the logo as its only logo; without it, an empty
logo list. A test of the branding page picks and removes the export logo.
