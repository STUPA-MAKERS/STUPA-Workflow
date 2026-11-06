---
id: "000495"
title: A public page holds the accessibility statement
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - backend/app/modules/admin
---

# A public page holds the accessibility statement

The route `/barrierefreiheit` must show the Erklärung zur Barrierefreiheit without a login.
The statement must state the conformance status, the parts that are not accessible and why,
the date of the last check, the feedback route and the Schlichtungsstelle.

Reason: § 10 L-BGG and the L-BGG-DVO require this statement for every website of a public
body.
