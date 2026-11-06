---
id: "000344"
title: Markdown images are re-encoded
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/files
  - backend/app/modules/media
---

# Markdown images are re-encoded

An image for Markdown must be re-encoded with Pillow. The upload must accept only PNG, JPEG,
GIF and WebP, and it must never accept SVG.

Reason: The re-encode removes a polyglot or a payload in the metadata.
