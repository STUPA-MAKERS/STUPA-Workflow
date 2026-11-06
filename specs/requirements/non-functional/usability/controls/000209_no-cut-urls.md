---
id: "000209"
title: URLs, IBANs and e-mail addresses are never cut
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# URLs, IBANs and e-mail addresses are never cut

A URL, an IBAN and an e-mail address must wrap and stay selectable. They must never be cut with
an ellipsis. A URL must be a real link that opens in a new tab with `rel="noopener"`.
