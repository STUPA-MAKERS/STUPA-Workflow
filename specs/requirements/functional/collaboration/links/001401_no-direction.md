---
id: "001401"
title: A link has no direction
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/links/service.py
scope:
  - backend/app/modules/links
  - frontend/src/app/features/links
---

# A link has no direction

A link must show in `Verknüpft` (`Linked`) of both of its elements. A person who may remove the
link must be able to remove it from either element. The removal must remove the link from both
elements.

Reason: A link connects two pieces of work. When it shows only on the element that made it, the
other element looks as if it had no link.

Test: A backend unit test links A to B, reads the links of B, and removes the link from B.
