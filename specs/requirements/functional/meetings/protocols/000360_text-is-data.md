---
id: "000360"
title: Protocol text is data, never code
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - typst/typst_service/document.py
  - typst/typst_service/markdown.py
scope:
  - backend/app/modules/protocol
  - typst/
---

# Protocol text is data, never code

The render service must turn the Markdown into JSON data before Typst sees it. No part of the
text must run as code.
