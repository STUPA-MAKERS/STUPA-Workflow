---
id: "002744"
title: The hosts of a Postfach need the deploy settings
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
---

# The hosts of a Postfach need the deploy settings

The deploy setting `TICKET_MAIL_HOST_ALLOWLIST` names the hosts that the IMAP host and the SMTP
host of a Postfach can have. The save of a different host must answer 422
`mail_host_not_allowed`. With an empty list the save must refuse each host.

Reason: A host that an admin sets freely lets the server open a connection to each internal host
(002514).

Test: A unit test saves a Postfach whose IMAP host is not in the list and expects 422.
