---
id: "000202"
title: Dialogs and toasts are on the top layer
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/vendor/ui-kit/src/lib/dialog/dialog.component.ts
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Dialogs and toasts are on the top layer

A dialog and a toast must open on the top layer above every other surface.
