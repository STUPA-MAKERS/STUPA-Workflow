---
id: "000169"
title: Attachments can be dropped
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/vendor/ui-kit/src/lib/file-drop/file-drop.directive.ts
  - frontend/vendor/ui-kit/src/lib/file-drop/drop-overlay.component.ts
scope:
  - backend/app/modules/files
  - frontend/src/app/shared
---

# Attachments can be dropped

Every attachment target must use the drop zone of the kit (ui-kit:002281). The upload and the
checks of the files stay with the server.
