---
id: "000360"
title: Protocol text is data, never code
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/protocol
  - typst/
---

# Protocol text is data, never code

The render service turns the Markdown into JSON data before Typst sees it. No part of the
text runs as code.
