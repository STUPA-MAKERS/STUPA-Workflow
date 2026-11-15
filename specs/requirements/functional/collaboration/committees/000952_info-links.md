---
id: "000952"
title: An Info link has a label and a web address
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/gremien/test_gremium_info.py:test_invalid_links_give_422"
implementation:
  - backend/app/modules/gremien_overview/schemas.py
  - frontend/src/app/features/gremien/gremium-info-dialog
scope:
  - backend/app/modules/gremien_overview
  - frontend/src/app/features/gremien
---

# An Info link has a label and a web address

Each link of the Info tab must have a label of 1 to 80 characters and a URL with the scheme
`https`, `http` or `mailto`. The server must refuse every other scheme with 422. The list must
keep the order that the editor sets. A Gremium must have at most 30 links. A link must open in
a new tab with `rel="noopener"` (000209).

Reason: A `javascript:` or `data:` address in a shared list is an attack on every reader.

Test: A backend test of the schemes and the limits. A component test of the order.
