---
id: "002162"
title: A switch between sections shows the new section at once
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/shell/src/route-motion.spec.ts:routeMotion"
implementation:
  - frontend/vendor/ui-kit/shell/src/route-motion.ts
  - frontend/vendor/ui-kit/src/styles/motion.scss
scope:
  - frontend/vendor/ui-kit/shell
---

# A switch between sections shows the new section at once

A navigation to another section (another first part of the path, for example from the bottom
bar or the rail) must not start a view transition. The new section must replace the old one
in the next frame, like the tabs of a native app. A navigation inside a section keeps its push
and pop on a phone.

Reason: A view transition holds a picture of the old page until the new page has rendered. A
section switch renders a whole new page, so the fade stood still for that time and then jumped.
The pill of the bar was in the picture and moved late.

Test: `route-motion.spec.ts` of the kit checks that a navigation to another section gives no
motion, and that a navigation inside a section gives push or pop.
