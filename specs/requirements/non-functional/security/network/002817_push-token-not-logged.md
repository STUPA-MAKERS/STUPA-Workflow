---
id: "002817"
title: An access log holds no token of a path
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - deploy/web/nginx.conf
  - backend/app/logging_config.py
scope:
  - deploy/web/nginx.conf
  - backend/app/logging_config.py
---

# An access log holds no token of a path

The access log of nginx and the access log of the API must not hold the token of a request to
`/api/push/actions/{token}` or to `/api/calendar/{token}.ics`. A log line must keep the path up to
the token and must replace the token with a fixed mask.

Reason: The token is the only right of the request. A push token stays valid for seven days
(002509), and a calendar token until the person makes a new one. A log line with the token gives
the action or the feed to each person who reads the log.

Test: A test of the nginx configuration and a unit test of the API log filter each log such a
request and expect the mask and no token in the line.
