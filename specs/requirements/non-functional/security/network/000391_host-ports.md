---
id: "000391"
title: Only two ports are bound on the host
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - deploy/docker-compose.yml
scope:
  - deploy/
---

# Only two ports are bound on the host

Only `web` (`127.0.0.1:8080`) and `postgres` (`127.0.0.1:5433`) must bind host ports, both on
loopback. No other service must publish a port.
