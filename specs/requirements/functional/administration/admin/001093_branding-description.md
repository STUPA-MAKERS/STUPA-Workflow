---
id: "001093"
title: The branding holds the description of the platform
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/admin/test_page_head.py:test_the_description_comes_from_the_branding_with_a_language_fallback"
  - "backend/tests/unit/modules/admin/test_page_head.py:test_the_description_is_capped"
  - "backend/tests/unit/modules/admin/test_page_head.py:test_the_manifest_takes_the_description_of_the_branding"
implementation:
  - backend/app/modules/site_config/branding.py
  - backend/app/modules/admin/page_head.py
  - backend/app/modules/admin/site_config_service.py
  - frontend/src/app/pages/admin/branding/branding-editor.component.html
scope:
  - backend/app/modules/site_config
  - backend/app/modules/admin
  - frontend/src/app/pages/admin/branding
---

# The branding holds the description of the platform

The page "Texte" of the branding must have a field "Beschreibung" per language, of at most
300 characters. The page head, the link preview and the PWA manifest must use it. An empty
language must use the text of German, and an empty field must use a built-in text that names
no platform.

Reason: The description names the platform to a person who has not opened it yet. A fixed
text with a platform name is wrong for every other branding.

Test: Unit tests check the fallback, the cap and the description of the manifest.
