---
id: "001080"
title: A download of a viewable file opens the file viewer
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/shared/viewer/file-open.service.spec.ts:FileOpenService"
implementation:
  - frontend/src/app/shared/viewer
scope:
  - frontend/src/app
---

# A download of a viewable file opens the file viewer

A download button or link must open the file in the file viewer of the kit when the viewer can
show the file. The viewer can show a PDF and a raster image (PNG, JPEG, GIF, WebP, AVIF, BMP).
Every other format must download as before, for example XLSX, CSV, ICS and archives. This
applies to every place in the app, for example:

- the attachments of an Antrag, of a ticket and of a chat message,
- the Antrag PDF,
- the PDF export of a Haushaltsplan,
- the protocol PDFs (internal, public, draft) and the public protocol pages,
- the receipt of an invoice and of a booking (001083),
- the logos of a CD variant and of the branding (001083).

The top bar of the viewer must have a download button that downloads the shown file under its
server name. A click with Ctrl, Cmd, Shift or the middle button must keep the default of the
browser.

Reason: A person who clicks a download button mostly wants to read the file. A download puts a
copy on the device and opens a second program. The viewer shows the file on the page, and the
download stays one click away.

Test: Unit test of the open service: a PDF and an image open the viewer, an XLSX downloads.
Component tests of the pages above: the button calls the open service.
