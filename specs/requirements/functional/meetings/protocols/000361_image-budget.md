---
id: "000361"
title: A protocol shows at most 48 images
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/protocol
  - backend/app/modules/media
scope:
  - backend/app/modules/protocol
  - backend/app/modules/media
---

# A protocol shows at most 48 images

A protocol PDF must hold at most 48 images, 8 MiB each and 24 MiB in total. A missing image or
an image over the limit must be left out.
