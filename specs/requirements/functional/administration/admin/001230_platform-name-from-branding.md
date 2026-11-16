---
id: "001230"
title: Every visible name of the platform comes from the branding
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/test_platform_name.py:test_no_visible_text_names_the_old_product_name"
  - "backend/tests/unit/modules/admin/test_page_head.py:test_an_empty_branding_gives_the_built_in_names_and_description"
  - "backend/tests/unit/modules/notifications/test_notifications_service.py:test_send_magic_link_builtin_fallback_in_english"
implementation:
  - backend/app/modules/site_config/names.py
  - backend/app/settings.py
  - frontend/src/app/core/i18n/catalog/de.json
  - frontend/src/app/core/i18n/catalog/en.json
  - frontend/src/index.html
  - frontend/public/manifest.webmanifest
scope:
  - backend/app
  - frontend/src
  - frontend/public
  - mcp/antragsplattform_mcp
  - typst
---

# Every visible name of the platform comes from the branding

A text that a person sees must name the platform by the app name of the active branding.
This covers the pages, the mails, the PDFs, the page head and the PWA manifest. Where the
branding is empty or cannot reach the text, the text must use the built-in name
"STUPA Workflow". This covers the page before the branding loads, the built-in head and
manifest files, the default sender name of a mail and the title of the API documentation.
No visible text may use the name "Antragsplattform".

Reason: An installation runs under its own name. A fixed product name in one place shows a
name that the admin cannot change and that the platform no longer uses.

Test: A unit test searches the sources of the frontend, the backend, the MCP server and the
PDF service for the old name. Unit tests check the built-in name of the page head and of a
mail without a branding.
