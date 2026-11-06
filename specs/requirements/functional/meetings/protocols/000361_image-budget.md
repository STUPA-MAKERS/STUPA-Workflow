---
id: "000361"
title: A protocol shows at most 48 images
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/protocol
  - backend/app/modules/media
---

# A protocol shows at most 48 images

A protocol PDF holds at most 48 images, 8 MiB each and 24 MiB in total. A missing image or an
image over the limit is left out.
