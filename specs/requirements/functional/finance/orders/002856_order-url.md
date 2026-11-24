---
id: "002856"
title: The link of a Bestellung is an http or https address
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/orders
  - frontend/src/app/pages/applications
---

# The link of a Bestellung is an http or https address

The `url` of a Bestellung must start with `http://` or `https://` and must have at most 2000
characters. The server must answer a different value with 422 `order_url_invalid`. The frontend
must open the link in a new tab with `rel="noopener noreferrer"`. The server must not call the
address.

Reason: A link with a different scheme, for example `javascript:`, runs code in the page. A call
from the server opens a way into the internal network.

Test: A backend unit test refuses `javascript:alert(1)` and `ftp://x` and accepts an https
address. A frontend test reads `rel` and `target` of the link.
