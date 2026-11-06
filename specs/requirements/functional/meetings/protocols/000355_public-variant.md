---
id: "000355"
title: A non-public TOP gives a second PDF
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/protocol/public.py
  - backend/app/modules/protocol/service.py
  - backend/worker/protocol.py
scope:
  - backend/app/modules/protocol
---

# A non-public TOP gives a second PDF

If a TOP is non-public, the finalize must render an internal PDF and a public PDF. The public
PDF must replace the non-public TOP texts and votes with a placeholder and must keep the
numbering. Only the public PDF must go to the mailing list.
