---
id: "001303"
title: The navigation leads a signed-in person to the public pages
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/layout/nav.service.ts
  - frontend/vendor/ui-kit/shell/src/nav-rail
  - frontend/vendor/ui-kit/shell/src/bottom-bar
scope:
  - frontend/src/app/layout
  - frontend/vendor/ui-kit/shell
---

# The navigation leads a signed-in person to the public pages

For a signed-in person, the navigation must have the entry "Öffentlich" as the last entry of
the main entries: in the rail inside the area that scrolls, on the phone in "Mehr". The entry
must open and close the links to the public pages "Protokolle" (`/protocols`), "Beschlüsse"
(`/decisions`) and "Kalender" (`/public-calendar`), each only while its feature
is on. The entry must be closed at first and must open by itself on one of these pages. The
menu "Hilfe" must not link the public pages.

Reason: The public start page `/` holds the only other links to these pages, and it leads a
signed-in person to the activity page.
