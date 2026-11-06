---
id: "000181"
title: Uploaded files are scanned
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/files
  - backend/app/modules/media
  - backend/app/modules/admin
---

# Uploaded files are scanned

Every uploaded file must pass the ClamAV scan before a user can download it. This includes
images and logos.
