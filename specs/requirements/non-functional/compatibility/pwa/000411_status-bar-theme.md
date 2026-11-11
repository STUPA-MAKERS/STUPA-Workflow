---
id: "000411"
title: The status bar follows the theme
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/vendor/ui-kit/src/lib/theme/theme.service.spec.ts:ThemeService"
implementation:
  - frontend/src/index.html
  - frontend/vendor/ui-kit/src/lib/theme/theme.service.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - frontend/src/index.html
---

# The status bar follows the theme

`index.html` must have one `theme-color` per colour scheme. The app must set both to the page
background of the chosen theme.

While "Hoher Kontrast" (000605) is on, the app must set both to black (`#000000`), in the
light and in the dark theme, because the page of that mode is black. When the mode goes off,
the colour of the chosen theme must apply again.

Reason: A status bar in another colour than the page is a coloured band above the app, and
in "Hoher Kontrast" it is a fifth colour.

Test: `frontend/vendor/ui-kit/src/lib/theme/theme.service.spec.ts`.
