---
id: "000198"
title: Neu and Speichern float at the bottom
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - frontend/vendor/ui-kit/src/lib/fab
  - frontend/vendor/ui-kit/shell/src/fab-link.directive.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Neu and Speichern float at the bottom

"Neu" must be a floating button at the bottom, on the desktop and on the phone. "Speichern"
must be a floating button at the bottom. It must show only while there are unsaved changes.
Neither button must be in the header.

The desktop start page is the exception: "Antrag stellen" stands in the tab line of the work
list (000650).

A page that creates different items in more than one section is the second exception: each
create button stands in the head of its section. Examples are Gruppen-Zuordnung and the roles
of a Gremium in Verwaltung.
