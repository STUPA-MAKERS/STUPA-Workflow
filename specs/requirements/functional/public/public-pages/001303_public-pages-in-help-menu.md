---
id: "001303"
title: The help menu leads a signed-in person to the public pages
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/features/help/help-menu/help-menu.component.html
scope:
  - frontend/src/app/features/help
---

# The help menu leads a signed-in person to the public pages

For a signed-in person, the menu "Hilfe" in the rail and in "Mehr" on the phone must link the
public pages "Protokolle" (`/protocols`), "Beschlüsse" (`/decisions`) and "Öffentlicher Kalender"
(`/public-calendar`), each only while its feature is on. The statement "Barrierefreiheit" stays
in the menu "Barrierefreiheit".

Reason: The public start page `/` holds the only links to these pages, and it leads a
signed-in person to the activity page.
