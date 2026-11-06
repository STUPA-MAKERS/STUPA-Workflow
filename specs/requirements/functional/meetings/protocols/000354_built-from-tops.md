---
id: "000354"
title: The protocol is built from the TOP texts
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/protocol/markdown.py
  - backend/app/modules/protocol/service.py
scope:
  - backend/app/modules/protocol
---

# The protocol is built from the TOP texts

When the meeting has TOPs, the protocol must be the TOP texts with their vote results, in the
agenda order. Each TOP must be a top-level heading without "TOP n". The renderer numbers them.
