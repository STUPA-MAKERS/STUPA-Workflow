---
id: "000355"
title: A non-public TOP gives a second PDF
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/protocol
---

# A non-public TOP gives a second PDF

If a TOP is non-public, the finalize renders an internal PDF and a public PDF. The public PDF
replaces the non-public TOP texts and votes with a placeholder and keeps the numbering. Only
the public PDF goes to the mailing list.
