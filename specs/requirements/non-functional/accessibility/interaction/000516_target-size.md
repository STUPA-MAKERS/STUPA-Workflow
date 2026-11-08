---
id: "000516"
title: A target is at least 24 by 24 px
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/src/app/axe-routes.contract.spec.ts:axeRouteSweep"
implementation:
  - frontend/e2e/06-axe.spec.ts
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A target is at least 24 by 24 px

A control must have a target of at least 24 × 24 CSS px, or a space of 24 px around it with
no other target. Text links in a sentence are an exception.

Reason: WCAG 2.5.8.
