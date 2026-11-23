---
id: "002706"
title: Each Bereich has its own Kategorien
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# Each Bereich has its own Kategorien

A Bereich must hold its own ordered list of Kategorien. A ticket must have at most one Kategorie
of its Bereich. The Bereich `Plattform` must have the fixed Kategorien `Fehler`, `Frage`, `Idee`
and `Barriere`, and an admin must not be able to change them.

Reason: The four kinds of a report describe feedback on the platform and fit no other team. The
accessibility report needs the kind `Barriere` on every installation (000497).

Test: A unit test sets a Kategorie of a different Bereich on a ticket and expects 422. A second
test renames a Kategorie of `Plattform` and expects 409.
