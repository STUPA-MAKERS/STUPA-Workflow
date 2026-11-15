---
id: "000972"
title: The web proxy takes the client address only from the edge
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - deploy/web/nginx.conf
  - deploy/docker-compose.yml
  - deploy/.env.example
scope:
  - deploy/
---

# The web proxy takes the client address only from the edge

The web proxy must read the client address from `X-Forwarded-For` only when the request comes
from an address in `TRUSTED_PROXY_IPS`. The deployment sets `TRUSTED_PROXY_IPS` to the exact
address of the edge proxy. The web proxy must send the api exactly one client address and must
drop every address that the client sent. Without `TRUSTED_PROXY_IPS` the web proxy must trust
no forwarded header.

Reason: The file `nginx.conf` comes from the repository, so an address that a person edits into
it is lost at the next release. A deployment then widens `FORWARDED_ALLOW_IPS` to whole private
ranges, and each machine in the LAN can fake the client address and bypass the rate limits
(§NF/security/network/000392).

Test: A deploy test sends a request with a faked `X-Forwarded-For` from an address outside
`TRUSTED_PROXY_IPS` and finds the address of the sender in the rate-limit key.
