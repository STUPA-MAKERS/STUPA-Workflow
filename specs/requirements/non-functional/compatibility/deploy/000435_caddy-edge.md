---
id: "000435"
title: Caddy is the edge proxy
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - deploy/README.md
  - deploy/web/nginx.conf
scope:
  - deploy/
---

# Caddy is the edge proxy

An external Caddy must terminate TLS and must proxy to the `web` service.
