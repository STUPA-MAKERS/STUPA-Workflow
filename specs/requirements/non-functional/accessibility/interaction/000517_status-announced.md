---
id: "000517"
title: A status message is announced
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/vendor/ui-kit/src/lib/announce/announcer.spec.ts:Announcer"
  - "frontend/vendor/ui-kit/src/lib/toast/toast.service.spec.ts:ToastService"
implementation:
  - frontend/vendor/ui-kit/src/lib/announce/announcer.ts
  - frontend/vendor/ui-kit/src/lib/toast/toast.service.ts
  - frontend/vendor/ui-kit/src/lib/search-pill/search-pill.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A status message is announced

A toast, a save result, a load error and a result count must be in a live region. The live
region must not move the focus.

Reason: WCAG 4.1.3. A screen reader user does not see a toast.
