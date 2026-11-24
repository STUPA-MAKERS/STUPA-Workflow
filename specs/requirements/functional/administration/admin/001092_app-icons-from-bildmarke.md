---
id: "001092"
title: The app icons follow the Bildmarke
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/admin/test_page_head.py:test_the_manifest_icons_follow_the_bildmarke"
  - "backend/tests/unit/modules/admin/test_page_head.py:test_a_wortmarke_alone_gives_no_app_icon"
  - "backend/tests/unit/modules/admin/test_page_head.py:test_an_app_icon_is_an_opaque_square_of_its_size"
  - "backend/tests/unit/modules/admin/test_page_head.py:test_the_apple_icon_and_the_favicon_follow_the_uploads"
implementation:
  - backend/app/modules/site_config/brand_images.py
  - backend/app/modules/admin/site_config_service.py
  - backend/app/modules/admin/router/branding_router.py
  - frontend/src/app/core/branding/branding.service.ts
scope:
  - backend/app/modules/site_config
  - backend/app/modules/admin
  - frontend/src/app/core/branding
---

# The app icons follow the Bildmarke

The icons of the PWA manifest and the iOS home screen icon must show the uploaded Bildmarke
on an opaque white square. A maskable icon must keep the mark inside the inner 60 % of the
square. Without a Bildmarke they must be the built-in icons. The tab icon must be the
uploaded favicon, else the built-in one.

Reason: The icon of an installed app is the most visible mark of the platform on a phone.
Android cuts a maskable icon to a circle, and iOS fills a transparent area with black.

Test: Unit tests check the icon URLs of the manifest and the size and pixels of an icon.
