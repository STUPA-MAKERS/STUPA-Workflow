---
id: "002160"
title: A scroll event runs no change detection
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/scroll-listeners.contract.spec.ts:scrollListenersContract"
implementation:
  - frontend/vendor/ui-kit/src/lib/scroll-fade/scroll-fade.directive.ts
  - frontend/vendor/ui-kit/src/lib/data-table/data-table.component.ts
  - frontend/vendor/ui-kit/src/lib/side-sheet/side-sheet.component.ts
  - frontend/vendor/ui-kit/src/lib/tab-pager/tab-pager.component.ts
  - frontend/src/app/shared/ui/chat/chat.component.ts
  - frontend/src/app/features/public-meeting/public-meeting.component.ts
scope:
  - frontend/src/app
  - frontend/vendor/ui-kit
---

# A scroll event runs no change detection

A component must listen to `scroll` with a native, passive listener (`addEventListener`). A
template must not bind `(scroll)`, and a host must not bind `scroll` or `window:scroll`. The
listener must change the view only through a signal.

Reason: Without zone.js (002002) a template or host listener still marks its view and schedules
a check of the app on each event. A phone sends a scroll event in each frame, so each frame of a
scroll and of a page change checked the whole app.

Test: A contract test reads every template and component of the app and of the kit and fails on
a `(scroll)` or `window:scroll` binding.
