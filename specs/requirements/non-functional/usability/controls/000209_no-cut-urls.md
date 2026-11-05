---
id: "000209"
title: URLs, IBANs and e-mail addresses are never cut
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - frontend/src/app/
  - ui-kit
---

# URLs, IBANs and e-mail addresses are never cut

A URL, an IBAN and an e-mail address wrap and stay selectable. They are never cut with an
ellipsis. A URL is a real link that opens in a new tab with `rel="noopener"`.
