---
id: "003112"
title: A template has no comments
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "frontend/src/app/core/templates/template-style.spec.ts:no comments"
implementation:
  - frontend/src/app
scope:
  - frontend/src/app
  - frontend/vendor/ui-kit
---

# A template has no comments

A component template must not contain an HTML comment. The reason for a part of a template
belongs in the spec that the part implements.

Reason: A comment in a template repeats the markup in prose and goes out of date when the
markup changes, while the spec stays the one place of the rule.

Test: `frontend/src/app/core/templates/template-style.spec.ts`: no `.html` file below
`src/app` contains `<!--`.
