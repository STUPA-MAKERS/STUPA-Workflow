---
id: "000356"
title: A failed render keeps the draft
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/protocol
---

# A failed render keeps the draft

The render runs before the commit. A render error rolls back, and the protocol stays a draft.
The upload and the mail run only after the commit.
