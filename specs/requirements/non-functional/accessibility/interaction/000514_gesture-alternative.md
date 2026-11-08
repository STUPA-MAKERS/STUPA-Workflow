---
id: "000514"
title: Each gesture has a single tap alternative
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/src/app/shared/ui/chat/chat.component.spec.ts:ChatComponent"
  - "frontend/vendor/ui-kit/src/lib/press-select/press-select.directive.spec.ts:PressSelectDirective"
  - "frontend/src/app/shared/ui/pull-refresh/refresh-menu.spec.ts:refreshMenuSection"
implementation:
  - frontend/src/app/shared/ui/chat/chat.component.html
  - frontend/src/app/shared/ui/pull-refresh/refresh-menu.ts
  - frontend/vendor/ui-kit/src/lib/press-select/press-select.directive.ts
  - frontend/src/app/pages/expenses/expenses.component.html
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.html
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Each gesture has a single tap alternative

A swipe, a long press and a pull must have an alternative with one tap or one click, for
example a menu entry.

Reason: WCAG 2.5.1. Some persons cannot do a swipe or hold a press.
