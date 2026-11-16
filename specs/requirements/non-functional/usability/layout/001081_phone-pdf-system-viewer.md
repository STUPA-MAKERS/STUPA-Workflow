---
id: "001081"
title: A PDF on a phone opens in the system viewer
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/shared/viewer/file-open.service.spec.ts:FileOpenService"
implementation:
  - frontend/src/app/shared/viewer
scope:
  - frontend/src/app
---

# A PDF on a phone opens in the system viewer

On a device with a coarse pointer, a PDF must open in a new tab with its inline preview, so the
system PDF viewer shows it. An image must open in the file viewer of the kit on every device.

Reason: A phone browser does not show a PDF in a frame. Android Chrome shows an empty frame, and
iOS Safari shows only the first page.

Test: Unit test of the open service with `(pointer: coarse)`: a PDF opens a new tab with
`?inline=true`, an image opens the viewer.
