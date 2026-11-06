---
id: "000356"
title: A failed render keeps the draft
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/protocol
---

# A failed render keeps the draft

The finalize must set the protocol to `rendering`, and the worker must render it. A transient
render error must retry, up to `pdf_max_tries`. A permanent error must set the protocol to
`draft` again. The upload and the mail must run only after a successful render.
