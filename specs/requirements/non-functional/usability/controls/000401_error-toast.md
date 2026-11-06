---
id: "000401"
title: Errors show as a toast
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/core/api/api-client.service.ts
  - frontend/vendor/ui-kit/src/lib/toast/toast.service.ts
scope:
  - frontend/src/app/
---

# Errors show as a toast

The frontend must show an API error (`ProblemDetail`) in a toast through `ToastService`.
