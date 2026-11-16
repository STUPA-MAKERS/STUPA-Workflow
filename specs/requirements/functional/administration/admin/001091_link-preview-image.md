---
id: "001091"
title: The link preview shows the Bildmarke
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/admin/test_page_head.py:test_the_preview_image_is_the_built_in_icon_without_a_mark"
  - "backend/tests/unit/modules/admin/test_page_head.py:test_the_preview_image_takes_the_bildmarke_else_the_wortmarke"
  - "backend/tests/unit/modules/admin/test_page_head.py:test_the_image_routes_serve_the_branding_images"
  - "backend/tests/unit/modules/admin/test_page_head.py:test_the_image_routes_answer_404_without_an_image"
implementation:
  - backend/app/modules/site_config/brand_images.py
  - backend/app/modules/admin/page_head.py
  - backend/app/modules/admin/router.py
scope:
  - backend/app/modules/site_config
  - backend/app/modules/admin
---

# The link preview shows the Bildmarke

The image of a link preview must be the uploaded Bildmarke on a white square of 512 pixels.
Without a Bildmarke it must be the uploaded Wortmarke on that square. Without both it must
be the built-in app icon. The image URL must change with every save of the branding.

Reason: A messenger shows a small square or round image. A square mark stays readable
there, and a new URL makes a messenger fetch the new image.

Test: Unit tests check the image URL for each case and the pixels of the square.
