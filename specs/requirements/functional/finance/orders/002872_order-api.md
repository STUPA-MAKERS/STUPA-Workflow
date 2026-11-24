---
id: "002872"
title: The Bestellungen have their own API
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/orders/router.py
  - mcp/antragsplattform_mcp/tools/orders.py
scope:
  - backend/app/modules/orders
---

# The Bestellungen have their own API

The API must have these routes: `GET /api/applications/{id}/orders`, `POST
/api/applications/{id}/orders`, `GET /api/orders`, `GET /api/orders/{id}`, `PATCH
/api/orders/{id}`, `POST /api/orders/{id}/status` and `DELETE /api/orders/{id}`. Each error must
be a problem+json answer.

Reason: One fixed set of routes serves the Antrag detail, the list and the MCP server
(F/integrations/mcp/001200).

Test: A backend integration test calls each route once.
