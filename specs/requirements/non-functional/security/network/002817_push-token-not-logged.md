---
id: "002817"
title: The access log holds no push action token
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - deploy/web/nginx.conf
scope:
  - deploy/web/nginx.conf
---

# The access log holds no push action token

The access log of nginx must not hold the token of a request to `/api/push/actions/`. The log line
must keep the path up to that prefix and must replace the token with a fixed mask.

Reason: The token is the only right of the request and stays valid for seven days (002509). A log
line with the token gives the action to each person who reads the log.

Test: A test of the nginx configuration sends a push action request and expects the mask and no
token in the log line.
