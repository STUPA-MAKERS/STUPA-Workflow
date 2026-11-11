---
id: "000221"
title: The Android navigation bar has the manifest colour
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "backend/tests/unit/modules/admin/test_admin_extra_cov.py:test_manifest_contrast_scheme_takes_black_bars"
implementation:
  - backend/app/modules/admin/site_config_service.py
  - frontend/vendor/ui-kit/src/lib/theme/theme.service.ts
scope:
  - frontend/public/manifest.webmanifest
  - backend/app/
---

# The Android navigation bar has the manifest colour

On Android, the navigation bar of the installed app takes the `theme_color` of the manifest.
The `theme_color` must be the `surface-3` colour.

The API must serve the manifest in three colour schemes: light, dark (`?scheme=dark`) and
"Hoher Kontrast" (`?scheme=contrast`), whose `theme_color` is black (`#000000`). The app must
link the manifest of the scheme in effect, and that of "Hoher Kontrast" while that mode
(000605) is on.

Android copies the colour into the installed app and reads the manifest again about once a
day. The navigation bar therefore follows a change of the scheme with that delay, not at
once. The app cannot shorten it.

Reason: The navigation bar meets the bottom bar of the app, and a manifest has no variant
per colour scheme.

Test: `backend/tests/unit/modules/admin/test_admin_extra_cov.py`.
