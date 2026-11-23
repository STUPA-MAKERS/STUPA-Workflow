---
id: "002741"
title: One address opens at most 20 tickets an hour by mail
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# One address opens at most 20 tickets an hour by mail

The platform must make at most 20 new tickets an hour from the mails of one address. A mail
above the limit must stay in the inbox until a later run takes it.

Reason: A broken machine or an attack must not fill the ticket list and the mail accounts of the
team in minutes. The mail waits, so nothing gets lost.

Test: A unit test imports 21 new mails of one address and expects 20 tickets and one mail left
in the inbox.
