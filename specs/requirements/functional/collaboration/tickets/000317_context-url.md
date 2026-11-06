---
id: "000317"
title: A ticket context keeps only platform pages
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A ticket context keeps only platform pages

The context URL of a ticket must keep only a page of the platform. Any other URL must be
dropped.
