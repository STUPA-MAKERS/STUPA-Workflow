---
id: "003100"
title: The pretix and Mollie clients call only allowed hosts
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# The pretix and Mollie clients call only allowed hosts

The deploy setting `PRETIX_HOST_ALLOWLIST` must name the hosts that the pretix address can have.
The save of an address with a different host must answer 422 `pretix_host_not_allowed`, and
with an empty list the save must refuse each address. The Mollie client must call only
`api.mollie.com`. Both clients must not follow a redirect.

Reason: pretix can run in the internal network, and an address that an admin sets freely lets
the server call each internal host (002514).

Test: A backend unit test saves a pretix address whose host is not in the list and expects 422.
