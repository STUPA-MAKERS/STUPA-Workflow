---
id: "000495"
title: A public page holds the accessibility statement
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/src/app/features/accessibility/accessibility-statement.component.spec.ts:AccessibilityStatementComponent"
  - "backend/tests/unit/modules/admin/test_admin_branding.py:test_the_accessibility_statement_defaults_to_the_built_in_draft"
implementation:
  - frontend/src/app/features/accessibility/accessibility-statement.component.ts
  - frontend/src/app/pages/admin/branding/branding-editor.component.ts
  - backend/app/modules/admin/statement.py
  - backend/app/modules/admin/branding.py
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - backend/app/modules/admin
---

# A public page holds the accessibility statement

The route `/accessibility` must show the Erklärung zur Barrierefreiheit without a login.
The statement must state the conformance status, the parts that are not accessible and why,
the date of the last check, the feedback route and the Schlichtungsstelle.

Reason: § 10 L-BGG and the L-BGG-DVO require this statement for every website of a public
body.
