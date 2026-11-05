---
id: "000344"
title: Markdown images are re-encoded
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/files
  - backend/app/modules/media
---

# Markdown images are re-encoded

An image for Markdown is re-encoded with Pillow. Only PNG, JPEG, GIF and WebP are accepted.
SVG is never accepted.

Reason: The re-encode removes a polyglot or a payload in the metadata.
