---
id: "000404"
title: Markdown images are outside erasure and export
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/media
  - backend/app/modules/privacy
scope:
  - backend/app/modules/media
  - backend/app/modules/privacy
---

# Markdown images are outside erasure and export

An uploaded Markdown image has no uploader. The erasure, the anonymization and the data export
must not touch it.
