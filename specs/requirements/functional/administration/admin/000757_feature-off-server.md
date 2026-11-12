---
id: "000757"
title: A feature that is off is closed on the server
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules
  - frontend/src/app
  - backend/worker
  - mcp
---

# A feature that is off is closed on the server

While a feature is off, each API route of the feature must answer 404 with the problem code
`feature_disabled`, for every person and for every token. The worker must not run the jobs of the
feature and must not send its mails. The MCP server must pass the 404 on. The answer must not
depend on a permission, so an admin also gets the 404.

Reason: The server decides on access, not the UI. A feature that is only hidden stays open
through the API and through an agent.

Test: A backend unit test for each feature switches it off and calls one read route and one write
route of the feature as admin. Each call gets 404 with `feature_disabled`. A worker test runs the
cron of a feature that is off and finds no mail and no change.
