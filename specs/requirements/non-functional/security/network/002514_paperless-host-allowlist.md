---
id: "002514"
title: The Paperless address needs a host from the deploy settings
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
---

# The Paperless address needs a host from the deploy settings

The deploy setting `PAPERLESS_HOST_ALLOWLIST` names the hosts that the Paperless address can
have. The save of an address with a different host must answer 422 `paperless_host_not_allowed`.
With an empty list the save must refuse each address. The client must not follow a redirect.

Reason: Paperless often runs in the internal network. An address that an admin sets freely
lets the server call each internal host.

Test: A unit test saves an address whose host is not in the list and expects 422.
