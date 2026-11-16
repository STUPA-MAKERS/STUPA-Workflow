---
id: "001090"
title: The page head follows the branding before any script runs
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/admin/test_page_head.py:test_the_head_names_the_platform_by_the_branding"
  - "backend/tests/unit/modules/admin/test_page_head.py:test_an_empty_branding_gives_the_built_in_names_and_description"
  - "backend/tests/unit/modules/admin/test_page_head.py:test_the_head_escapes_the_admin_texts"
  - "backend/tests/unit/modules/admin/test_page_head.py:test_the_page_head_route_serves_the_fragment_without_auth"
  - "frontend/src/app/core/pwa/install-metadata.spec.ts:indexHtml"
implementation:
  - backend/app/modules/admin/page_head.py
  - backend/app/modules/admin/router.py
  - deploy/web/nginx.conf
  - frontend/src/index.html
scope:
  - backend/app/modules/admin
  - deploy/web
  - frontend/src/index.html
  - frontend/src/app/core/branding
---

# The page head follows the branding before any script runs

The HTML of every page of the app must name the platform by the active branding before a
script runs. This covers the title, the description, the app name of iOS, the icons and the
Open Graph and Twitter tags of a link preview. The web server must fill these tags into the
page from `GET /api/page-head`. If the API does not answer, the page must show the
built-in tags. The service worker must get the built file without the filled tags.

Reason: A link preview in a messenger or a search engine reads the HTML and runs no script.
A name that the app sets at runtime never reaches the preview. The service worker compares
the hash of the file with the build, so a changed file stops every update of the app.

Test: Unit tests render the head with and without a branding and with admin text that holds
HTML. A frontend test checks the stub and the include in `index.html`.
