---
id: "000358"
title: The protocol mail carries the PDF
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/protocol
  - backend/app/modules/notifications
scope:
  - backend/app/modules/protocol
  - backend/app/modules/notifications
---

# The protocol mail carries the PDF

The protocol mail must go to the active Gremium members and the extra mailing addresses,
filtered by the protocol mail setting. The PDF must be an attachment, not a link.
