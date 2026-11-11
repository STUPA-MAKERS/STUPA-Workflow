---
id: "000677"
title: A public page has a title of 28 px
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/src/app/shared/ui-sweep.spec.ts:loginTitle"
implementation:
  - frontend/src/app/pages/login
  - frontend/src/app/features/apply
  - frontend/src/app/features/public-protocols
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A public page has a title of 28 px

The title of a public page must have a font size of 28 px and must stand at the start of the
content column. This applies also to the login page. The start page keeps its centred
welcome title, and the error pages keep their small title below the status number.

Reason: Antrag stellen, Öffentliche Protokolle and the accessibility statement use 28 px. The
login page uses 22 px.

Test: A style test of the login page expects the title to use the same size token as the
apply page.
